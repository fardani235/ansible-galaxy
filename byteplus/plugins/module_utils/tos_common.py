# Copyright fardani235
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import datetime
import hashlib
import hmac

import urllib3

from urllib.parse import urlparse, quote

from byteplussdkcore.configuration import Configuration
from byteplussdkcore.rest import RESTClientObject, ApiException

try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode


_DEFAULT_TIMEOUT = (30, 300)


def _hmac_sha256(key, msg):
    return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()


def _signing_key(sk, date, region, service):
    k = _hmac_sha256(sk.encode('utf-8'), date)
    k = _hmac_sha256(k, region)
    k = _hmac_sha256(k, service)
    return _hmac_sha256(k, 'request')


def _canonical_query(query):
    if not query:
        return ''
    pairs = []
    for k in sorted(query):
        pairs.append('{}={}'.format(
            quote(str(k), safe='-_.~'),
            quote(str(query[k]), safe='-_.~'),
        ))
    return '&'.join(pairs)


def _sign_v4_bytes(path, method, headers, body_bytes, query, ak, sk, region,
                   service, session_token=None):
    """Bytes-safe SigV4 signer mirroring byteplussdkcore.signv4.SignerV4.sign.

    Why: the SDK's signer calls body.encode('utf-8') on the body argument,
    which breaks for any non-UTF-8 binary payload (images, archives, etc.).
    """
    if not path:
        path = '/'
    if method != 'GET' and 'Content-Type' not in headers:
        headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=utf-8'

    if body_bytes is None:
        body_bytes = b''

    fmt_date = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    # TOS expects the S3-style x-tos-date header (not the BytePlus OpenAPI
    # X-Date). The bare "Date" header is also set so non-AWS-style clients
    # work, but only x-tos-date is included in the signed canonical headers.
    headers['X-Tos-Date'] = fmt_date

    body_hash = hashlib.sha256(body_bytes).hexdigest()
    headers['X-Tos-Content-Sha256'] = body_hash
    if session_token:
        headers['X-Tos-Security-Token'] = session_token

    signed_headers = {}
    for key, value in headers.items():
        lk = key.lower()
        if lk in ('content-type', 'content-md5', 'host') or lk.startswith('x-tos-'):
            signed_headers[lk] = value

    if 'host' in signed_headers:
        v = signed_headers['host']
        if ':' in v:
            host_part, port = v.split(':', 1)
            if port in ('80', '443'):
                signed_headers['host'] = host_part

    signed_str = ''
    for key in sorted(signed_headers):
        signed_str += '{}:{}\n'.format(key, signed_headers[key])
    signed_headers_string = ';'.join(sorted(signed_headers))

    canonical_request = '\n'.join([
        method, path, _canonical_query(query),
        signed_str, signed_headers_string, body_hash,
    ])

    credential_scope = '/'.join([fmt_date[:8], region, service, 'request'])
    signing_str = '\n'.join([
        'TOS4-HMAC-SHA256', fmt_date, credential_scope,
        hashlib.sha256(canonical_request.encode('utf-8')).hexdigest(),
    ])
    key = _signing_key(sk, fmt_date[:8], region, service)
    signature = hmac.new(key, signing_str.encode('utf-8'), hashlib.sha256).hexdigest()

    headers['Authorization'] = (
        'TOS4-HMAC-SHA256 Credential={}/{}, SignedHeaders={}, Signature={}'
        .format(ak, credential_scope, signed_headers_string, signature)
    )


def _quote_key(object_key):
    return quote(object_key, safe='/')


class TOSClient(object):
    def __init__(self, access_key, secret_key, region, session_token=None,
                 request_timeout=_DEFAULT_TIMEOUT):
        # Build a local Configuration without mutating the process-wide default;
        # Configuration.set_default() would leak credentials across clients.
        self.config = Configuration()
        self.config.ak = access_key
        self.config.sk = secret_key
        self.config.region = region
        if session_token:
            self.config.session_token = session_token
        self.rest_client = RESTClientObject(self.config)
        self._request_timeout = request_timeout

    def _get_endpoint(self, bucket_name=None):
        region = self.config.region
        if bucket_name:
            return 'https://{bucket}.tos-{region}.bytepluses.com'.format(
                bucket=bucket_name, region=region)
        return 'https://tos-{region}.bytepluses.com'.format(region=region)

    def _sign_and_request(self, method, url, path, headers, body, query_params,
                          _preload_content=True):
        parsed = urlparse(url)
        headers['Host'] = parsed.netloc

        if body is None:
            body_bytes = b''
        elif isinstance(body, bytes):
            body_bytes = body
        else:
            body_bytes = body.encode('utf-8')

        query_dict = {}
        if query_params:
            for k, v in query_params.items():
                query_dict[k] = str(v)

        _sign_v4_bytes(
            path=path,
            method=method,
            headers=headers,
            body_bytes=body_bytes,
            query=query_dict,
            ak=self.config.ak,
            sk=self.config.sk,
            region=self.config.region,
            service='tos',
            session_token=getattr(self.config, 'session_token', None) or None,
        )

        # Bypass byteplussdkcore.rest.RESTClientObject.request — it only knows
        # about JSON / form-urlencoded / multipart bodies and rejects raw bytes
        # with a "Cannot prepare a request message" error. TOS needs to send
        # arbitrary binary payloads (including empty PUT/DELETE bodies), so we
        # talk to the underlying urllib3 pool manager directly.
        if query_params:
            url = url + '?' + urlencode(query_params)

        send_body = None
        if method in ('PUT', 'POST', 'PATCH'):
            send_body = body_bytes

        if isinstance(self._request_timeout, tuple):
            timeout = urllib3.Timeout(
                connect=self._request_timeout[0],
                read=self._request_timeout[1],
            )
        else:
            timeout = urllib3.Timeout(total=self._request_timeout)

        resp = self.rest_client.pool_manager.urlopen(
            method=method,
            url=url,
            body=send_body,
            headers=headers,
            preload_content=_preload_content,
            timeout=timeout,
            retries=False,
        )

        if not 200 <= resp.status <= 299:
            raise ApiException(http_resp=resp)

        return resp

    def head_bucket(self, bucket_name):
        url = self._get_endpoint(bucket_name)
        headers = {}
        try:
            self._sign_and_request('HEAD', url, '/', headers, None, None)
            return True
        except ApiException as e:
            if e.status == 404:
                return False
            raise

    def create_bucket(self, bucket_name, acl=None):
        url = self._get_endpoint(bucket_name)
        headers = {'Content-Type': 'application/octet-stream'}
        if acl:
            headers['x-tos-acl'] = acl
        self._sign_and_request('PUT', url, '/', headers, b'', None)

    def delete_bucket(self, bucket_name):
        url = self._get_endpoint(bucket_name)
        headers = {'Content-Type': 'application/octet-stream'}
        self._sign_and_request('DELETE', url, '/', headers, b'', None)

    def head_object(self, bucket_name, object_key):
        quoted = _quote_key(object_key)
        url = self._get_endpoint(bucket_name) + '/' + quoted
        path = '/' + quoted
        headers = {}
        try:
            resp = self._sign_and_request('HEAD', url, path, headers, None, None)
            return True, dict(resp.getheaders())
        except ApiException as e:
            if e.status == 404:
                return False, {}
            raise

    def put_object(self, bucket_name, object_key, body, content_type=None):
        quoted = _quote_key(object_key)
        url = self._get_endpoint(bucket_name) + '/' + quoted
        path = '/' + quoted
        headers = {'Content-Type': content_type or 'application/octet-stream'}
        self._sign_and_request('PUT', url, path, headers, body, None)

    def delete_object(self, bucket_name, object_key):
        quoted = _quote_key(object_key)
        url = self._get_endpoint(bucket_name) + '/' + quoted
        path = '/' + quoted
        headers = {'Content-Type': 'application/octet-stream'}
        self._sign_and_request('DELETE', url, path, headers, b'', None)



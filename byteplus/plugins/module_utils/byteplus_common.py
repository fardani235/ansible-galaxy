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

from byteplussdkcore.configuration import Configuration
from byteplussdkcore.universal import UniversalApi, UniversalInfo
from byteplussdkcore.rest import ApiException


class BytePlusClient:
    def __init__(self, access_key, secret_key, region):
        config = Configuration()
        config.ak = access_key
        config.sk = secret_key
        config.region = region
        Configuration.set_default(config)
        self.api = UniversalApi()

    def _make_request(self, action, params, method='POST'):
        content_type = 'application/json' if method == 'POST' else 'text/plain'
        info = UniversalInfo(
            method=method,
            service='dns',
            version='2018-08-01',
            action=action,
            content_type=content_type,
        )
        try:
            return self.api.do_call(info, params)
        except ApiException as e:
            raise Exception("BytePlus API error for {}: {}".format(action, e.reason))
        except Exception as e:
            raise Exception("BytePlus API call {} failed: {}".format(action, str(e)))

    def resolve_zone_id(self, zone_id=None, domain_name=None):
        if zone_id:
            return zone_id
        if domain_name:
            resp = self._make_request('ListZones', {
                'Key': domain_name,
                'SearchMode': 'exact',
                'PageSize': 100,
            }, method='GET')
            zones = resp.get('Zones', []) if resp else []
            for zone in zones:
                if zone.get('ZoneName') == domain_name:
                    return zone['ZID']
            raise ValueError("Domain '{}' not found in BytePlus DNS".format(domain_name))
        raise ValueError("Either zone_id or domain_name is required")

    def create_record(self, zone_id, host, record_type, value, ttl=600, line='default',
                      weight=None, remark=None, client_token=None):
        params = {
            'ZID': zone_id,
            'Host': host,
            'Type': record_type,
            'Value': value,
            'TTL': ttl,
            'Line': line,
        }
        if weight is not None:
            params['Weight'] = weight
        if remark:
            params['Remark'] = remark
        if client_token:
            params['ClientToken'] = client_token
        return self._make_request('CreateRecord', params)

    def delete_record(self, record_id):
        return self._make_request('DeleteRecord', {'RecordID': record_id})

    def update_record(self, record_id, host=None, line=None, record_type=None,
                      value=None, ttl=None, weight=None, remark=None):
        params = {'RecordID': record_id}
        if host is not None:
            params['Host'] = host
        if line is not None:
            params['Line'] = line
        if record_type is not None:
            params['Type'] = record_type
        if value is not None:
            params['Value'] = value
        if ttl is not None:
            params['TTL'] = ttl
        if weight is not None:
            params['Weight'] = weight
        if remark is not None:
            params['Remark'] = remark
        return self._make_request('UpdateRecord', params)

    def list_records(self, zone_id, host=None, record_type=None,
                     page_number=1, page_size=50):
        params = {'ZID': zone_id}
        if host:
            params['Host'] = host
        if record_type:
            params['Type'] = record_type
        if page_number:
            params['PageNumber'] = page_number
        if page_size:
            params['PageSize'] = page_size
        return self._make_request('ListRecords', params, method='GET')

    def query_record(self, record_id):
        return self._make_request('QueryRecord', {'RecordID': record_id}, method='GET')

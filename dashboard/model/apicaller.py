from urllib.request import urlopen
import re
import json
import numbers
import pandas as pd
import numpy as np
from datetime import timedelta, datetime

from flask import current_app, url_for, session

from .utils import replace_latitude_longitude, isnumber
from .db import get_db, query_db


class APICaller:
    def __init__(self, latitude, longitude, delta_mins):
        self.latitude = latitude
        self.longitude = longitude
        self.delta_mins = delta_mins
        self.logger_name = 'Base Data'
        self.db_tablename = 'mytable' #for mytable_daily, use mytable as "table" and key as "daily"
        self.data_list = ['key1','key2'] 
        self.key_as_table = False
        self.API_base_url = 'https://apiurl/'
        self.data_dict = {'data_name':pd.DataFrame({})}
        self.restriction_query_dict = {}
        self.restriction_columns_dict = {}
        self.update_boolean = False


    def update_latitude(self, latitude):
        if isnumber(latitude, self.logger_name, 'latitude'):
            self.latitude = latitude


    def update_longitude(self, longitude):
        if isnumber(longitude, self.logger_name, 'longitude'):
            self.longitude = longitude


    def update_delta_mins(self, delta_mins):
        if isnumber(delta_mins, self.logger_name, 'delta_mins'):
            self.delta_mins = delta_mins

    def update_position_and_update_delay_from_session(self):
        update_latitude(session['latitude'])
        update_longitude(session['longitude'])
        update_delta_mins(session['delta_mins'])

    def load_API(self):
        _API_url = replace_latitude_longitude(
            self.API_base_url, self.latitude, self.longitude
            )
        try:
            _API_call_raw_data = urlopen(_API_url)
        except URLError as e:
            current_app.logger.info(
                f'{self.logger_name} | Error loading API {e}')
            return {'API_loading_status' : False}
        else:
            current_app.logger.info(
                f'{self.logger_name} | Unexpected error loading API')
            return {'API_loading_status' : False}

        return {'API_loading_status' : True, 'raw_data' : _API_call_raw_data}

    def additional_API_check(self, API_raw_data_dict):
        return True

    def decode_API_raw_data(self, API_raw_data):
        _raw_data_decoded = API_raw_data.read().decode('utf-8','replace')
        return json.loads(_raw_data_decoded)

    def clean_decoded_API_data(self, json_data):
        #cleaning

        self.data_dict = {
            'key1': pd.DataFrame(),
            'key2': pd.DataFrame()
        }
        return self.data_dict


    def add_additional_data(self):
        for key in self.data_dict.keys():
            self.data_dict[key].loc[:,'latitude'] = self.latitude
            self.data_dict[key].loc[:,'longitude'] = self.longitude
            self.data_dict[key].loc[:, self.db_tablename + '_date'] \
                = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return self.data_dict


    def restrict_data(self):
        if self.restriction_query_dict != {}:
            for dict_key, restrict_query in self.restriction_query_dict.items():
                self.data_dict[dict_key] = self.data_dict[dict_key].query(restrict_query)
        if self.restriction_columns_dict != {}:
            for dict_key, columns_list in self.restriction_columns_dict.items():
                self.data_dict[dict_key] = self.data_dict[dict_key][columns_list]
        return self.data_dict


    def load_and_clean_data(self):
        _raw_data_dict = self.load_API()
        if self.additional_API_check(_raw_data_dict) is False:
            _raw_data_dict['API_loading_status'] = False
        if _raw_data_dict['API_loading_status'] is True:
            #TODO : exceptions to capture
            current_app.logger.info(
                f'{self.logger_name} | Cleaning data')
            _data_json = self.decode_API_raw_data(_raw_data_dict['raw_data'])
            self.clean_decoded_API_data(_data_json)
            self.add_additional_data()
            self.restrict_data()
            self.update_boolean = True
            current_app.logger.info(
                f'{self.logger_name} | Data Cleaned')
            return {'load_and_clean_data_status' : True}
        else:
            return {'load_and_clean_data_status' : False}


    def save_data_dict(self):
        current_app.logger.info(f'{self.logger_name} | Saving data to db')
        _sql_con = get_db()
        if self.key_as_table is True:
            table_list = [self.db_tablename + '_' + str(key) for key in self.data_list]
        else : 
            table_list = self.db_tablename
        for key, table in zip(self.data_list, table_list):
            self.data_dict[key].to_sql(
                name = table,
                con = _sql_con,
                if_exists='append',
                index=False
            )
        current_app.logger.info(f'{self.logger_name} | Data saved to db')
        return True



    def check_if_db_is_not_empty_and_get_last_date(self, key=''):
        # note : if several keys in data_list, loads only with the first key
        if self.key_as_table is False: 
            _full_tablename = self.db_tablename
        else:
            if key == '':
                key = self.data_list[0]
            _full_tablename = self.db_tablename + '_' + key

        _query_string = (
            f'SELECT {self.db_tablename}_date FROM {_full_tablename} \
                WHERE latitude = {self.latitude} \
                AND longitude = {self.longitude} \
                ORDER BY {self.db_tablename}_date DESC \
                LIMIT 1;'
                )
        _query = query_db(_query_string)
        print(_query_string)
        if _query != []:
            for date_query in _query:
                return {'existing_entry_status' : True, 'last_date' : date_query[0]}
        else:
            return {'existing_entry_status' : False}

    def read_last_available_updated_data(self, delta_mins = 0):
        _out_dict = {}
        if delta_mins == 0:
            delta_mins = self.delta_mins
        for key in self.data_list:
            _out_dict[key] = self.read_last_available_data_by_key(additional_key=key)
        print(_out_dict)
        return _out_dict


    def read_last_available_data_by_key(self, additional_key=''):
         #TODO : rewrite with SQL MAX function after first commit
        current_app.logger.info(f'{self.logger_name} | Reading last entry in db {self.db_tablename} {additional_key}')
        check_db_dict = self.check_if_db_is_not_empty_and_get_last_date(key=additional_key)
        if check_db_dict['existing_entry_status'] is True:
            _last_update_date = check_db_dict['last_date']
        else:
            raise KeyError("DB should not be empty")

        _sql_con = get_db()
        if (self.key_as_table is True) & (additional_key != ''):
            _full_tablename = self.db_tablename + '_' + additional_key
        else:
            _full_tablename = self.db_tablename
            
        _query_last_update_string = f"SELECT * FROM {_full_tablename} \
                        WHERE latitude ={self.latitude} \
                        AND longitude = {self.longitude} \
                        AND {self.db_tablename}_date >= '{_last_update_date}';"
        print(_query_last_update_string)
        return pd.read_sql(
            _query_last_update_string,
            con=_sql_con
        )

    def update_db_with_new_data(self):
        self.load_and_clean_data()
        if self.update_boolean is True:
            self.save_data_dict()
            self.update_boolean = False
            return True
        else: # TODO : to be checked / necessary case??
            #error loading API => read older entry
            current_app.logger.info(f'{self.logger_name} | Error loading API : read older entry')
            self.data_dict = self.read_last_available_updated_data(delta_mins = 10000)
            return self.data_dict


    def check_and_update_db(self):
        _query_db_last_entry_dict = self.check_if_db_is_not_empty_and_get_last_date()
        if _query_db_last_entry_dict['existing_entry_status'] is True:
            current_app.logger.info(f'{self.logger_name} | existing entries in db')
            _last_update_date = _query_db_last_entry_dict['last_date']
        else:
            current_app.logger.info(f'{self.logger_name} | no existing entries in db')
            _last_update_date = datetime.now() - timedelta(minutes=self.delta_mins + 1)
        #if entry is too old : update db
        if (datetime.now() - _last_update_date) > timedelta(minutes = self.delta_mins):
            current_app.logger.info(f'{self.logger_name} | Updating db')
            self.update_db_with_new_data()
        #else : read_db and save to data_dict
        else:
            current_app.logger.info(f'{self.logger_name} | Reading last updated data')
            self.data_dict = self.read_last_updated_data()

    
    def print_data(self):
        for key,data_pdf in self.data_dict.items():
            print('\n',key)
            print(data_pdf)

    def prepare_data_for_html(self):
        return {
            'key_1':pd.DataFrame(),
            'key2':pd.DataFrame()
            }

    def data_to_html(self):
        return 'True'

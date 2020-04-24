import json
import boto3
import os
import datetime
import uuid
import logging
import re
import random
import whois
import time
from ipwhois import IPWhois
logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3_BUCKET = os.environ.get('S3_BUCKET', None)
ALERT_FILE = os.environ.get('ALERT_FILE', None)
ALERT_DETAIL_FILE = os.environ.get('ALERT_DETAIL_FILE', None)
SCAN_RESULT_FILE = os.environ.get('SCAN_RESULT_FILE', None)
API_KEY = os.environ.get('API_KEY', None)
MAX_RESULTS = 10
SCANS_TABLE = os.environ.get('SCANS_TABLE', None)


# Severity map: 4 possible values, Low to Critical
SEVERITY_MAP=['Low','Medium','High','Critical']
        
def unpack_exception(e):
    if not isinstance(e, BaseException):
        return None
    if not hasattr(e,'args'):
        return None
    if len(e.args) != 1:
        return None
    if not isinstance(e.args[0], dict):
        return None
    ex = e.args[0]
    if not ex.get('code', None):
        return None
    if not ex.get('err', None):
        return None
    return ex

def authenticate(event):
        # Check environment variables
        if not S3_BUCKET or not ALERT_FILE or not ALERT_DETAIL_FILE or not SCAN_RESULT_FILE or not API_KEY:
            raise RuntimeError({'code': 500,'err': 'Environment variables not set'})

        # Check Method
        # logger.info(f'event received and is: {dir(event)}')
        if 'httpMethod' not in event or event['httpMethod'] != 'GET':
            raise ValueError({'code': 400,'err': f'HTTP Method error'})
    
        # Check API KEY
        headers = event.get('headers', None)
        if not headers:
            raise ValueError({'code': 403, 'err': 'No Headers'})
        authorization = headers.get('Authorization', None)
        if not authorization:
            raise ValueError({'code': 403, 'err': 'No Authorization'})
        auth_reg = re.match('^Bearer ([\w+\-]*)$', authorization)
        # logger.info(f'Auth_Reg Groups is: {auth_reg.groups()}, len: {len(auth_reg.groups())}')
        if not auth_reg or len(auth_reg.groups()) != 1 or auth_reg.group(1) != API_KEY:
            raise ValueError({'code': 403, 'err': 'Invalid Authorization'})
        
        return

def domain(event, content):
    response = None
    try:
        # Check method and authenticate
        authenticate(event)

        # Check Domain
        query_string_parameters = event.get('queryStringParameters', None)
        if not query_string_parameters:
            raise ValueError({'code': 400, 'err': 'No domain provided'})

        domain = query_string_parameters.get('domain', None)
        if not domain:
            raise ValueError({'code': 400, 'err': 'No domain provided'})

        who = whois.whois(domain)
        if who:
            who['score'] = abs(hash(domain)) % 100
            response = {
                "statusCode": 200,
                "body": str(who)
            }
        else:
            response = {
                "statusCode": 404,
                "body": "Domain not found!"
            } 

    except Exception as e:
        ex_args = unpack_exception(e)
        if ex_args:
            response = {
                "statusCode": ex_args['code'],
                "body": ex_args['err']
            }
        else:
            response = {
                "statusCode": 500,
                "body": f"Input Error: {str(e)}"
            }    

    return response

def start_scan(event, content):
    response = None
    try:
        # Check method and authenticate
        authenticate(event)

        # Check parameters
        asset = None

        query_string_parameters = event.get('queryStringParameters', None)
        if query_string_parameters:
            hostname = query_string_parameters.get('hostname', None)

        if not hostname:
            raise ValueError({'code': 400, 'err': 'No hostname provided'})

        scan = {}
        scan['scan_id'] = str(uuid.uuid4())
        scan['status'] = "RUNNING"

        response = {
            "statusCode": 200,
            "body": json.dumps(scan)
        }
    except Exception as e:
        ex_args = unpack_exception(e)
        if ex_args:
            response = {
                "statusCode": ex_args['code'],
                "body": ex_args['err']
            }
        else:
            response = {
                "statusCode": 500,
                "body": f"Error: {str(e)}"
            }    

    return response

def check_scan(event, content):
    response = None
    try:
        # Check method and authenticate
        authenticate(event)

        # Check parameters
        scan_id = None

        query_string_parameters = event.get('queryStringParameters', None)
        if query_string_parameters:
            scan_id = query_string_parameters.get('scan_id', None)

        if not scan_id:
            raise ValueError({'code': 400, 'err': 'No scan_id provided'})

        # Initialize DynamoDB

        dynamo = boto3.resource('dynamodb')
        table = dynamo.Table(SCANS_TABLE)
        
        # Check if we already have this scan in DynamoDB - if yes return random,
        # if not return RUNNING (first time) and write it
        db_scan = table.get_item(Key={'scanId': scan_id})
        scan = {}
        scan['scan_id'] = scan_id

        if not db_scan or 'Item' not in db_scan:
            scan['status'] = "RUNNING"
            table.update_item(
                    Key={'scanId': scan_id},
                    UpdateExpression='set scanttl=:ttl',
                    ExpressionAttributeValues={':ttl': int(time.time())+600},
            )
        else:
            x = random.randint(0,100)
            if x > 60:
                scan['status'] = "RUNNING"
            else:
                scan['status'] = "COMPLETE"

        response = {
            "statusCode": 200,
            "body": json.dumps(scan)
        }

        response = {
            "statusCode": 200,
            "body": json.dumps(scan)
        }
    except Exception as e:
        ex_args = unpack_exception(e)
        if ex_args:
            response = {
                "statusCode": ex_args['code'],
                "body": ex_args['err']
            }
        else:
            response = {
                "statusCode": 500,
                "body": f"Error: {str(e)}"
            }    

    return response

def get_scan_results(event, content):
    response = None
    try:
        # Check method and authenticate
        authenticate(event)

        # Check parameters
        scan_id = None

        query_string_parameters = event.get('queryStringParameters', None)
        if query_string_parameters:
            scan_id = query_string_parameters.get('scan_id', None)

        if not scan_id:
            raise ValueError({'code': 400, 'err': 'No scan_id provided'})

        s3 = boto3.resource('s3')
        obj = s3.Object(S3_BUCKET, SCAN_RESULT_FILE)
        file_content = obj.get()['Body'].read().decode('utf-8')
        results = json.loads(file_content)

        scan = {}
        scan['scan_id'] = scan_id
        scan['status'] = "COMPLETE"
        scan['entities'] = results

        response = {
            "statusCode": 200,
            "body": json.dumps(scan)
        }

        response = {
            "statusCode": 200,
            "body": json.dumps(scan)
        }
    except Exception as e:
        ex_args = unpack_exception(e)
        if ex_args:
            response = {
                "statusCode": ex_args['code'],
                "body": ex_args['err']
            }
        else:
            response = {
                "statusCode": 500,
                "body": f"Error: {str(e)}"
            }    

    return response

def ip(event, content):
    response = None
    try:
        # Check method and authenticate
        authenticate(event)

        # Check IP
        query_string_parameters = event.get('queryStringParameters', None)
        if not query_string_parameters:
            raise ValueError({'code': 400, 'err': 'No ip provided'})

        ip = query_string_parameters.get('ip', None)
        if not ip:
            raise ValueError({'code': 400, 'err': 'No ip provided'})

        who = IPWhois(ip)
        r = who.lookup_rdap(depth=1)
        if who:
            r['score'] = abs(hash(ip)) % 100            
            response = {
                "statusCode": 200,
                "body": json.dumps(r)
            }
        else:
            response = {
                "statusCode": 404,
                "body": "IP not found!"
            } 


    except Exception as e:
        ex_args = unpack_exception(e)
        if ex_args:
            response = {
                "statusCode": ex_args['code'],
                "body": ex_args['err']
            }
        else:
            response = {
                "statusCode": 500,
                "body": f"Input Error: {str(e)}"
            }    

    return response

def get_alert_details(event, context):
    response = None
    try:
        # Check method and authenticate
        authenticate(event)

        # Check Severity filter
        alert_id = None

        query_string_parameters = event.get('queryStringParameters', None)
        if query_string_parameters:
            alert_id = query_string_parameters.get('alert_id', None)

        if not alert_id:
            raise ValueError({'code': 400, 'err': 'No alert_id provided'})

        s3 = boto3.resource('s3')
        obj = s3.Object(S3_BUCKET, ALERT_DETAIL_FILE)
        file_content = obj.get()['Body'].read().decode('utf-8')
        events = json.loads(file_content)

        now = int(datetime.datetime.utcnow().timestamp())

        alert = {}

        alert = events[random.randint(0,len(events)-1)]
        alert['created'] = now
        alert['alert_id'] = alert_id

        response = {
            "statusCode": 200,
            "body": json.dumps(alert)
        }
    except Exception as e:
        ex_args = unpack_exception(e)
        if ex_args:
            response = {
                "statusCode": ex_args['code'],
                "body": ex_args['err']
            }
        else:
            response = {
                "statusCode": 500,
                "body": f"Error: {str(e)}"
            }    

    return response


def change_alert_status(event, context):
    response = None
    try:
        # Check method and authenticate
        authenticate(event)

        # Check Severity filter
        alert_id = None

        query_string_parameters = event.get('queryStringParameters', None)
        if query_string_parameters:
            alert_id = query_string_parameters.get('alert_id', None)
            alert_status = query_string_parameters.get('alert_status', None)

        if not alert_id:
            raise ValueError({'code': 400, 'err': 'No alert_id provided'})

        if not alert_status:
            raise ValueError({'code': 400, 'err': 'No alert_status provided'})

        if alert_status not in ['ACTIVE', 'CLOSED']:
            raise ValueError({'code': 400, 'err': 'Invalid alert_status. Must be ACTIVE or CLOSED'})

        alert = {}
        now = int(datetime.datetime.utcnow().timestamp())
        alert['updated'] = now
        alert['alert_status'] = alert_status
        alert['alert_id'] = alert_id

        response = {
            "statusCode": 200,
            "body": json.dumps(alert)
        }
    except Exception as e:
        ex_args = unpack_exception(e)
        if ex_args:
            response = {
                "statusCode": ex_args['code'],
                "body": ex_args['err']
            }
        else:
            response = {
                "statusCode": 500,
                "body": f"Error: {str(e)}"
            }    

    return response


def get_alerts(event, context):
    response = None
    try:
        # Check method and authenticate
        authenticate(event)

        # Check Severity filter
        severity = None
        alert_type = None
        start_time = 0
        max_alerts = 0
        alert_status = None
        query_string_parameters = event.get('queryStringParameters', None)
        if query_string_parameters:
            severity = query_string_parameters.get('severity', None)
            start_time = int(query_string_parameters.get('start_time', 0))
            max_results = int(query_string_parameters.get('max_results', 0))
            alert_status = query_string_parameters.get('alert_status', None)
            alert_type = query_string_parameters.get('alert_type', None)

        if not max_results:
            max_results = MAX_RESULTS


        severities = SEVERITY_MAP
        if severity:
            severities = severity.split(',')
            if not all(s in SEVERITY_MAP for s in severities):
                raise ValueError(f'Severity must be a comma separated value including the following {",".join(SERVERITY_MAP)}')
        
        s3 = boto3.resource('s3')
        obj = s3.Object(S3_BUCKET, ALERT_FILE)
        file_content = obj.get()['Body'].read().decode('utf-8')
        events = json.loads(file_content)

        now = int(datetime.datetime.utcnow().timestamp())
        if not start_time or start_time >= now:
            start_time = now - 60

        alerts = []
        cnt = 0
        for e in events:
            # filters
            if severities and len(severities) > 0:
                if 'severity' not in e:
                    continue
                if e['severity'] not in severities:
                    continue
            if alert_type:
                if 'alert_type' not in e:
                    continue
                if e['alert_type'] != alert_type:
                    continue

            if alert_status:
                if 'alert_status' not in e:
                    continue
                if e['alert_status'] != alert_status:
                    continue

            e['created'] = random.randint(start_time, now)
            e['alert_id'] = str(uuid.uuid4())
            alerts.append(e)
            cnt += 1
            if cnt == max_results:
                break

        response = {
            "statusCode": 200,
            "body": json.dumps(alerts)
        }
    except Exception as e:
        ex_args = unpack_exception(e)
        if ex_args:
            response = {
                "statusCode": ex_args['code'],
                "body": ex_args['err']
            }
        else:
            response = {
                "statusCode": 500,
                "body": f"Error: {str(e)}"
            }    

    return response

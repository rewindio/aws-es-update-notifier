import json
import boto3
from botocore.exceptions import ClientError
import os
from slack import WebClient
from slack.errors import SlackApiError

boto_session = boto3.session.Session()
es_client = boto_session.client('es')
ssm_client = boto_session.client('ssm')
iam_client = boto_session.client('iam')

def get_aws_account_alias(iam_client):
    account_alias = None
    
    try:
        account_alias = iam_client.list_account_aliases()['AccountAliases'][0]
    except ClientError as ex:
        print("Unable to get current aws account ID: {}".format(ex.response['Error']['Code']))

    return account_alias

def get_slack_token(ssm_client, token_path):
    param_val = None

    try:
        response = ssm_client.get_parameter(Name=token_path, WithDecryption=True)
        param_val = response['Parameter']['Value']
    except ClientError as ex:
        print("Unable to retrieve parameter from parameter store: {}".format(ex.response['Error']['Code']))

    return param_val

def lambda_handler(event, context):
    domains = None

    try:
        domains = es_client.list_domain_names()
    except ClientError as ex:
        print("Unable to obtain list of ES domains: {}".format(ex.response['Error']['Code']))

    if domains:
        for domain in domains['DomainNames']:
            domain_props = None
            domain_name = domain['DomainName']
            print("ES Domain found " + domain_name + ". Checking for updates...")
            
            try:
                domain_props = es_client.describe_elasticsearch_domain(DomainName=domain_name)
            except ClientError as ex:
                print("Unable to describe domain: {}".format(ex.response['Error']['Code']))

            if domain_props:
                update_available = domain_props['DomainStatus']['ServiceSoftwareOptions']['UpdateAvailable']
                
                if update_available:
                    print("Update is available for domain " + domain_name)

                    current_version = domain_props['DomainStatus']['ServiceSoftwareOptions']['CurrentVersion']
                    update_version = domain_props['DomainStatus']['ServiceSoftwareOptions']['NewVersion']

                    domain_console_url = 'https://console.aws.amazon.com/es/home?region=' + boto_session.region_name + '#domain:resource=' + domain_name + ';action=dashboard'
                    es_release_notes_url = 'https://docs.aws.amazon.com/elasticsearch-service/latest/developerguide/release-notes.html#release-table'

                    slack_token = get_slack_token(ssm_client,os.environ['SLACK_TOKEN_SSM_PATH'])
                    slack_channel = os.environ['SLACK_CHANNEL']

                    if slack_token:
                        slack_client = WebClient(token=slack_token)

                        try:
                            response = slack_client.chat_postMessage(
                                channel=slack_channel,
                                blocks=[
                                            {
                                                "type": "section",
                                                "text": {
                                                    "type": "mrkdwn",
                                                    "text": "A new ElasticSearch cluster update is available\n*<" + domain_console_url + "|" + domain_name + ">*"
                                                }
                                            },
                                            {
                                                "type": "section",
                                                "fields": [
                                                    {
                                                        "type": "mrkdwn",
                                                        "text": "*AWS Account:*\n" + get_aws_account_alias(iam_client)
                                                    },
                                                    {
                                                        "type": "mrkdwn",
                                                        "text": "*Region:*\n" + boto_session.region_name
                                                    },
                                                    {
                                                        "type": "mrkdwn",
                                                        "text": "*Current Version:*\n" + str(current_version)
                                                    },
                                                    {
                                                        "type": "mrkdwn",
                                                        "text": "New Version:\n*<" + es_release_notes_url + "|" + str(update_version) + ">*"
                                                    }
                                                ]
                                            }
                                        ]
                            )
                        except SlackApiError as e:
                            # You will get a SlackApiError if "ok" is False
                            assert e.response["ok"] is False
                            assert e.response["error"]  # str like 'invalid_auth', 'channel_not_found'
                            print(f"Error posting to Slack: {e.response['error']}")
                else:
                    print("No update available for domain " + domain_name)

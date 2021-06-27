#!/bin/bash
from flask import Flask, request
from datetime import datetime
import boto3
import requests
import xxhash
import sys
from uhashring import HashRing


elb = boto3.client('elbv2', region_name='eu-central-1')
ec2 = boto3.client('ec2', region_name='eu-central-1')
PREFIX = "NoamRoyCloudCache-25"
app = Flask(__name__)
cache = dict()
ip_dict = dict()


# health check
def get_health_status():
    target_group = elb.describe_target_groups(
        Names=[PREFIX + "-tg"],
    )
    target_group_arn = target_group["TargetGroups"][0]["TargetGroupArn"]
    health = elb.describe_target_health(TargetGroupArn=target_group_arn)
    healthy = []
    for target in health["TargetHealthDescriptions"]:
        if target["TargetHealth"]["State"] != "unhealthy":
            healthy.append(target["Target"]["Id"])

    healthy_ips = []
    for node_id in healthy:
        public_ip = ec2.describe_instances(InstanceIds=[node_id])["Reservations"][0]["Instances"][0]["PublicIpAddress"]
        private_ip = ec2.describe_instances(InstanceIds=[node_id])["Reservations"][0]["Instances"][0]["PrivateIpAddress"]
        healthy_ips.append(public_ip)
        ip_dict[public_ip] = private_ip

    healthy_ips.sort()
    return healthy_ips


nodes_list = HashRing(nodes=get_health_status())


def update_nodes_list():
    nodes = get_health_status()

    for node_key in list(nodes_list.get_nodes()):
        if node_key not in nodes:
            nodes_list.remove_node(node_key)


def get_alt_node(key):
    node = nodes_list.get_node(key)
    nodes_list.remove_node(node)
    alt_node = nodes_list.get_node(key)
    nodes_list.add_node(node)

    return alt_node


@app.route('/', methods=['GET', 'POST'])
def home():
    return "Hello World!"


@app.route('/health-check', methods=['GET', 'POST'])
def health_check():
    return "I'M ALIVE"


@app.route('/save', methods=['GET', 'POST'])
def save():
    key = request.args.get('str_key')
    data = request.args.get('data')
    expiration_date = request.args.get('expiration_date')
    user_ip = request.remote_addr
    update_nodes_list()

    if user_ip in list(nodes_list.get_nodes()):
        cache[key] = (data, expiration_date)
        return {"cache": cache[key]}, 200
    else:
        return {"cache": "Permission denied"}, 403


@app.route('/load', methods=['GET', 'POST'])
def load():
    key = request.args.get('str_key')
    user_ip = request.remote_addr
    update_nodes_list()

    ans = "Key doesn't exist"
    if user_ip in list(nodes_list.get_nodes()):
        if key in cache:
            if int((datetime.now().date() - datetime.strptime(cache[key][1], '%Y-%m-%d').date()).total_seconds()) < 0:
                ans = cache[key]
            else:
                ans = ("Expiration time exceed", "")
        return {"cache": ans}, 200
    else:
        return {"cache": "Permission denied"}, 403


@app.route('/get', methods=['GET', 'POST'])
def get():
    key = request.args.get('str_key')
    update_nodes_list()
    key_v_node_id = xxhash.xxh64_intdigest(key) % 1024

    node = ip_dict[nodes_list.get_node(key_v_node_id)]
    alt_node = ip_dict[get_alt_node(key_v_node_id)]

    try:
        ans = requests.get(f'http://{node}:5000/load?str_key={key}')
    except:
        try:
            ans = requests.get(f'https://{alt_node}:5000/load?str_key={key}')
        except:
            response = ', '.join(ans.json().get('cache'))
            return response, 200

    if type(ans.json().get('cache')) == str:
        return ans.json().get('cache')

    response = ', '.join(ans.json().get('cache'))
    return response, 200


@app.route('/put', methods=['GET', 'POST'])
def put():
    key = request.args.get('str_key')
    data = request.args.get('data')
    expiration_date = request.args.get('expiration_date')

    try:
        datetime.strptime(expiration_date, "%Y-%m-%d")
    except ValueError:
        return "invalid date format, should be YYYY-MM-DD", 200

    update_nodes_list()
    key_v_node_id = xxhash.xxh64_intdigest(key) % 1024

    node = ip_dict[nodes_list.get_node(key_v_node_id)]
    alt_node = ip_dict[get_alt_node(key_v_node_id)]

    error1 = None
    error2 = None
    try:
        ans = requests.post(f'http://{node}:5000/save?str_key={key}&data={data}&expiration_date={expiration_date}')
    except:
        error1 = sys.exc_info()[0]

    try:
        ans = requests.post(f'http://{alt_node}:5000/save?str_key={key}&data={data}&expiration_date={expiration_date}')
    except:
        error2 = sys.exc_info()[0]

    if error1 is not None and error2 is not None:
        raise Exception(f'Error 1:{error1} \n Error 2: {error2}')

    if type(ans.json().get('cache')) == str:
        return ans.json().get('cache'), 200

    response = ', '.join(ans.json().get('cache'))
    return response, 200

#!/bin/bash
# debug
# set -o xtrace

KEY_NAME="Noam-Roy-CloudCaching-`date +'%N'`"
KEY_PEM=".pem/$KEY_NAME.pem"
ELB_NAME="NoamRoyCloudCache"
ELB_ROLE_NAME=$"elb-role-name-`date +'%N'`"
ELB_POLICY_NAME=$"ELBFullAccessPolicy-`date +'%N'`"
INSTANCE_PROFILE_NAME=$"InstanceProfile-`date +'%N'`"
AMI="ami-05f7491af5eef733a"

mkdir .pem
chmod 777 .pem
echo "create key pair $KEY_PEM to connect to instances and save locally"
aws ec2 create-key-pair --key-name $KEY_NAME | jq -r ".KeyMaterial" > $KEY_PEM

# secure the key pair
chmod 400 $KEY_PEM

SEC_GRP="my-sg-`date +'%N'`"

echo "setup firewall $SEC_GRP"
SEC_GRP_ID=$(aws ec2 create-security-group   \
    --group-name $SEC_GRP       \
    --description "Access my instances" | jq -r '.GroupId')

MY_IP=$(curl ipinfo.io/ip)
echo "setup rule allowing SSH access to $MY_IP only"
aws ec2 authorize-security-group-ingress        \
    --group-name $SEC_GRP \
    --port 22 --protocol tcp \
    --cidr $MY_IP/32

echo "create iam rule for elb access"
chmod 777 ec2-role-trust-policy.json
chmod 777 elb-policy.json
aws iam create-role --role-name $ELB_ROLE_NAME --assume-role-policy-document file://ec2-role-trust-policy.json
aws iam put-role-policy --role-name $ELB_ROLE_NAME --policy-name $ELB_POLICY_NAME --policy-document file://elb-policy.json
aws iam create-instance-profile --instance-profile-name $INSTANCE_PROFILE_NAME
aws iam add-role-to-instance-profile --instance-profile-name $INSTANCE_PROFILE_NAME --role-name $ELB_ROLE_NAME
sleep 10

for i in 1 2 3
do
  echo "Creating ec2 instance $i"
  RUN_INSTANCES=$(aws ec2 run-instances   \
      --image-id $AMI        \
      --iam-instance-profile Name=$INSTANCE_PROFILE_NAME \
      --instance-type t2.micro            \
      --key-name $KEY_NAME                \
      --security-groups $SEC_GRP)

  INSTANCE_ID=$(echo $RUN_INSTANCES | jq -r '.Instances[0].InstanceId')

  echo "Waiting for instance creation..."
  aws ec2 wait instance-running --instance-ids $INSTANCE_ID

  PUBLIC_IP=$(aws ec2 describe-instances  --instance-ids $INSTANCE_ID |
      jq -r '.Reservations[0].Instances[0].PublicIpAddress'
  )

  echo "New instance $INSTANCE_ID @ $PUBLIC_IP"
  mkdir instances
  touch instances/instances_id.txt
  chmod 777 -R instances
  echo $INSTANCE_ID >> instances/instances_id.txt

  echo "deploying code to production"
  scp -i $KEY_PEM -o "StrictHostKeyChecking=no" -o "ConnectionAttempts=60" app.py ubuntu@$PUBLIC_IP:/home/ubuntu/
  scp -r -i $KEY_PEM -o "StrictHostKeyChecking=no" -o "ConnectionAttempts=60" ~/.aws/ ubuntu@$PUBLIC_IP:/home/ubuntu/
  sleep 10
  echo "setup production environment"
  ssh -i $KEY_PEM -o "StrictHostKeyChecking=no" -o "ConnectionAttempts=60" ubuntu@$PUBLIC_IP <<EOF
      set -e
      sudo apt-get update
      sudo apt-get install build-essential python3.8 python3-pip python3-wheel awscli python3-flask -y
      pip install xxhash
      pip install requests
      pip install uhashring
      pip install boto3
      pip install --upgrade awscli
      # run app
      nohup flask run --host 0.0.0.0 &>/dev/null &
      exit
EOF
  sleep 10
done

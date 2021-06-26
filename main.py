import subprocess
import os
import elb
import sys

if __name__ == "__main__":
    elb.ensure_elb_setup_created()
    subprocess.call("./deploy_ec2.sh")

    if os.path.exists("instances/instances_id.txt"):
        f = open("instances/instances_id.txt", "r")
        # Getting the account details for the DB
        instance_id1 = f.readline().split('\n')[0]
        instance_id2 = f.readline().split('\n')[0]
        instance_id3 = f.readline().split('\n')[0]

        elb.register_instance_in_elb(instance_id1)
        elb.register_instance_in_elb(instance_id2)
        elb.register_instance_in_elb(instance_id3)

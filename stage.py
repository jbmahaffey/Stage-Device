#!/usr/bin/env python3

import sys
import csv
import os
import requests
import yaml
from cvprac.cvp_client import CvpClient
import argparse
import ssl
import logging
from jinja2 import Environment, FileSystemLoader
ssl._create_default_https_context = ssl._create_unverified_context

#################
# Main function #
#################
def Main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cvp', default='192.168.101.35', help='CVP Server IP')
    parser.add_argument('--username', default='cvpadmin', help='CVP username')
    parser.add_argument('--password', default='password123', help='Cloudvision password')
    parser.add_argument('--logging', default='', help='Logging levels info, error, or debug')
    parser.add_argument('--devlist', default='devices.csv', help='YAML/CSV file with list of approved devices.')
    parser.add_argument('--identifier', default='serial', help='How are you identifying valid devices?  Serial or MAC')
    args = parser.parse_args()

    # Only enable logging when necessary
    if args.logging != '':
        logginglevel = args.logging
        formattedlevel = logginglevel.upper()

        # Open logfile
        logging.basicConfig(format='%(asctime)s %(levelname)-8s %(message)s',filename='cvpmove.log', level=formattedlevel, datefmt='%Y-%m-%d %H:%M:%S')
    else:
        ()
        
    # Open variable file either csv or yaml
    filetype = args.devlist.split('.')
    
    if filetype[1] == 'yml':
        # Open YAML variable file
        with open(os.path.join(sys.path[0],args.devlist), 'r') as vars_:
            data = yaml.safe_load(vars_)
    
    elif filetype[1] == 'csv':
        devices = []
        with open(os.path.join(sys.path[0],args.devlist), 'r') as vars_:
            for line in csv.DictReader(vars_):
                devices.append(line)
        data = {'all': devices}
    
    else:
        logging.info('Please enter a valid file type.')

    # CVPRAC connect to CVP
    clnt = CvpClient()
    try:
        clnt.connect(nodes=[args.cvp], username=args.username, password=args.password)
    except:
        logging.error('Unable to login to Cloudvision')

    # Get devices from Undefined container in CVP and add their MAC to a list
    try:
        undefined = clnt.api.get_devices_in_container('Undefined')
    except:
        logging.error('Unable to get devices from Cloudvision.')

    undef = []
    if args.identifier == 'mac' or args.identifier == 'MAC':
        for unprov in undefined:
            undef.append(unprov['systemMacAddress'])
    else:
        for unprov in undefined:
            undef.append(unprov['serialNumber'])

    # Compare list of devices in CVP undefined container to list of approved devices defined in YAML file
    # If the the device is defined in the YAML file then provision it to the proper container
    for dev in data['all']:
        if args.identifier == 'mac' or args.identifier == 'MAC':
            if dev['mac'] in undef:
                device = clnt.api.get_device_by_mac(dev['mac'])
                try:
                    contain = Container(clnt, dev)
                except:
                    logging.error('Unable to determine if container exist')
                try:
                    deploy = Deploy(clnt, data, contain, device)
                    Execute(clnt, deploy['data']['taskIds'])
                except:
                    logging.error('Unable to move device to new container')
                try:
                    con = Configlet(clnt, dev, args.cvp, args.username, args.password)
                    if con != None and con != 'reconcile':
                        assign = AssignConfiglet(clnt, dev, con)
                        Execute(clnt, assign['data']['taskIds'])
                    else:
                        ()
                except:
                    logging.error('Unable to create configlet or assign it.')
                
        else:
            if dev['serial'] in undef:
                device = clnt.api.get_device_by_serial(dev['serial'])
                try:
                    contain = Container(clnt, dev)
                except:
                    logging.error('Unable to determine if container exist')
                try:
                    deploy = Deploy(clnt, data, contain, device)
                    Execute(clnt, deploy['data']['taskIds'])
                except:
                    logging.error('Unable to move device to new container')
                try:
                    con = Configlet(clnt, dev, args.cvp, args.username, args.password)
                    if con != None and con != 'reconcile':
                        assign = AssignConfiglet(clnt, dev, con)
                        Execute(clnt, assign['data']['taskIds'])
                    else:
                        ()
                except:
                    logging.error('Unable to create configlet or assign it.')


#############################################
# Check if container exist if not create it #
#############################################
def Container(clnt, data):
    try:
        if data['staging'] != '':
            staging = clnt.api.get_container_by_name(name=data['staging'])
            print(staging)
            if staging == None:
                clnt.api.add_container(container_name=data['staging'], parent_name='Tenant', parent_key='root')
                return 'success'
            else:
                return 'success'
        else:
            staging = clnt.api.get_container_by_name(name="staging")
            if staging == None:
                clnt.api.add_container(container_name='staging', parent_name='Tenant', parent_key='root')
                return 'success'
            else:
                return 'success'
    except:
        logging.info('Error getting staging container.')
        return 'Failure'


######################################
# Deploy device to staging container #
######################################
def Deploy(clnt, data, contain, device):
    try:
        if data['all'][0]['staging'] != '':
            if contain == 'success':            
                tsk = clnt.api.deploy_device(device=device, container=data['staging'])
                return tsk
        else:
            if contain == 'success':
                tsk = clnt.api.deploy_device(device=device, container='staging')
                return tsk
    except:
        logging.error('No container available')


###############################################
# Create base configlet with mgmt information #
###############################################
def Configlet(clnt, data, cvp, user, password):
    l = []
    try:
        config = clnt.api.get_configlets(start=0, end=0)
        if data['serial'] == '':
            ztp = clnt.api.get_device_by_mac(data['mac'])
        else:
            ztp = clnt.api.get_device_by_serial(data['serial'])
    except:
        logging.error('Unable to get list of configlets.')

    for configlet in config['data']:
        l.append(configlet['name'])

    if ztp['ztpMode'] == 'true' or data['ztp'] == 'true' or data['ztp'] == 'TRUE':
        #Render configuration template to push to cvp as a configlet
        try:
            THIS_DIR = os.path.dirname(os.path.abspath(__file__))
            j2_env = Environment(loader=FileSystemLoader(THIS_DIR),
                         trim_blocks=True)
            if data['mgmtvrf'] == 'default' or data['mgmtvrf'] == '':
                conf = j2_env.get_template('base.j2').render(hostname = data['hostname'], mgmtvrf = 'default', mgmtint = data['mgmtint'], mgmtip = data['mgmtip'], mgmtmask = data['mgmtmask'], mgmtgateway = data['mgmtgateway'], cvp=cvp)
            else:
                conf = j2_env.get_template('base.j2').render(hostname = data['hostname'], mgmtvrf = data['mgmtvrf'], mgmtint = data['mgmtint'], mgmtip = data['mgmtip'], mgmtmask = data['mgmtmask'], mgmtgateway = data['mgmtgateway'], cvp=cvp)
        except:
            logging.error('Unable to render template')
        
        #Push configlet to CVP
        try:
            if data['hostname'] + '_base' in l:
                devconf = clnt.api.get_configlet_by_name(name=data['hostname'] + '_base')
                usexisting = input('Configlet ' +  data['hostname'] + '_base already exist would you like to replace this configlet Y/N? ')
                if usexisting == 'y' or usexisting == 'Y' or usexisting == 'yes' or usexisting == 'Yes':
                    clnt.api.update_configlet(config=conf, key=devconf['key'], name=devconf['name'])
                    return devconf
                else:
                    logging.error('Configlet with the same name already exist and you have selected to not use the existing.  Please delete the existing configlet and try again.')
                    ()

            else:
                clnt.api.add_configlet(name=data['hostname'] + '_base', config=conf)
                cfgltdata = clnt.api.get_configlet_by_name(name=data['hostname'] + '_base')
                return cfgltdata

        except:
            logging.error('Unable to create configlet ' + str(data['hostname'] + '_cfglt'))

    #If the device is not setup to ztp then we will reconcile the device instead of create new configlet
    else:
        try:
            container = clnt.api.get_container_by_name(name=data['container'])
            ckey = container['key']
            login = 'https://{server}/cvpservice/login/authenticate.do'.format(server=cvp)
            resp = requests.post(login, headers={'content-type': 'application/json'}, json={'userId': user, 'password': password}, verify=False)
            jresp = resp.json()
            token = jresp['cookie']['Value']
            url = 'https://{server}/cvpservice/provisioning/containerLevelReconcile.do?containerId={container}&reconcileAll=false'.format(server=cvp, container=ckey)
            response = requests.get(url, auth=(user, password), headers={'Cookie': 'access_token=' + str(token)}, verify=False)
            if response.status_code == 200:
                reconcile = 'reconcile'
            return reconcile
        except:
            logging.error('Unable to reconcile container.')


##############################################
# function to assign configlet to new device #
##############################################
def AssignConfiglet(clnt, dev, con):
    try:
        device = clnt.api.get_device_by_mac(dev['mac'])
    except:
        logging.error('Unable to get device information from Cloudvision')
    cfglets = [{'name': dev['hostname'] + '_base', 'key': con['key']}]
    try:
        task = clnt.api.apply_configlets_to_device(app_name=dev['hostname'] + '_base', dev=device, new_configlets=cfglets)
        return task
    except:
        logging.error('Error applying configlet to device.')


###################################################################
# Function to run task if they are for the devices we provisioned #
###################################################################
def Execute(clnt, tasks):
    for task in tasks:
        try:
            clnt.api.execute_task(task_id=task)
        except:
            logging.info('Task ID ' + str(task) + ' is ' + ' failed to execute.')


#########################
# Execute Main function #
#########################
if __name__ == '__main__':
   Main()
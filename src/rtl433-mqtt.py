#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Simple wrapping script for translate RF433 switches
# clicks to the MQTT with optional integration with Home Assistant
# by Evgeniy Shumilov <evgeniy.shumilov@gmail.com>

import os
import sys
import json
import yaml
import asyncio
import argparse
import logging as l
#import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish
from datetime import datetime

appname = 'rtl433mqtt'
checkPeriod = 0.1
buff = {}
auth = {}
sections = ['unit', 'channel', 'button']
startts = int(datetime.now().timestamp())
subtypes = {1:'single', 2:'double', 3:'triple', 4:'quadruple', 5:'many'}

ap = argparse.ArgumentParser()
ap.add_argument('--config', help='Path to config file, default=config.yml', dest='config', default='config.yml', required=False)
ap.add_argument('--debug', help='Debug mode on if not empty, off by default', dest='debug', default='', required=False)
ap.add_argument('--dry-run', help='Dry-run mode (without sending to MQTT), default = True', dest='dryrun', default=True, required=False)
args = ap.parse_args()

if args.debug:
    l.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=l.DEBUG)
else:
    l.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=l.INFO)

l.info('Start working')
l.info('Load config %s' % args.config)
if os.path.exists(str(args.config)):
    with open(str(args.config), 'r') as conffile:
        try:
            conf = yaml.safe_load(conffile)
        except yaml.YAMLError as e:
            print(e)
    mainconf = conf.get(appname)
    mqttconf = conf.get('mqtt')
    
else:
    print('FATAL ERROR: Fail to found config file %s' % args.config)
    sys.exit(1)

dryrun = str(args.dryrun).lower()
if dryrun == 'false' or dryrun == 'no' or dryrun == '0':
    dryrun = False
    l.debug('DryRun mode is off')
    mqttuser = mqttconf.get('user')
    mqttpass = mqttconf.get('pass')
    if mqttuser and mqttpass:
        auth = {'username': mqttuser, 'password': mqttpass}
else:
    dryrun = True
    l.info('DryRun mode is on')

timegap = mainconf.get('timegap')
if not timegap:
    timegap = 0.5

def ts():
    return int(datetime.now().timestamp())

def lineParse(line=''):
    if line.startswith('{"time" ') and line.endswith('}'):
        l.debug('Processing %s' % line)
        try:
            res = json.loads(line)
            topic = '/rtl433/%s/%s/' % (res['model'], res['id'])
            for s in sections:
                if s in res:
                    topic += '_%s_%s' % (s, res[s])
            if 'state' in res:
                state = res['state']
            elif 'data' in res:
                state = res['data'].split(' ')[0]
            elif 'code' in res:
                state = res['code']
            else:
                state = '1'
            topic += '_' + state
            topic = topic.replace('/_', '/')
            for blitem in mainconf.get('blacklist'):
                if topic.startswith(blitem):
                    return None
            return topic
        except:
            l.warning('Fail to process %s' % line)
            return None
    else:
        return None

def mqttSend(topic, state, retain=True, qos=1):
    l.info('MQTT <- %s : %s' % (topic, state))
    if not dryrun:
        if auth:
            publish.single(topic,
                           payload=state,
                           hostname=mqttconf.get('host'),
                           port=mqttconf.get('port'),
                           client_id='rtl433mqtt',
                           auth=auth,
                           retain=retain,
                           qos=qos)
        else:
            publish.single(topic,
                           payload=state,
                           hostname=mqttconf.get('host'),
                           port=mqttconf.get('port'),
                           client_id='rtl433mqtt',
                           retain=retain,
                           qos=qos)

async def rtl433():
    proc = await asyncio.create_subprocess_shell(
        'rtl_433 -F json', stdout=asyncio.subprocess.PIPE)
    while True:
        data = await proc.stdout.readline()
        line = data.decode().rstrip()
        if line:
            topic = lineParse(line)
            if topic:
                l.debug('BUFFER <- %s' % topic)
                last = buff.get(topic)
                if last:
                    tdiff = datetime.now().timestamp() - last['ts']
                    if tdiff < timegap:
                        buff[topic]['ts'] = datetime.now().timestamp()
                        buff[topic]['count'] += 1
                else:
                    buff[topic] = {'ts':datetime.now().timestamp(), 'count':1}

async def buffChecker():
    while True:
        ts = datetime.now().timestamp()
        for t in list(buff.keys()):
            if ts - buff[t]['ts'] > timegap:
                length = ''
                if buff[t]['count'] <=6:
                    length = 'short'
                elif buff[t]['count'] <= 12:
                    length = 'medium'
                elif buff[t]['count'] > 12:
                    length = 'long'
                if length:
                    mqttSend(t + '_' + length, length, qos=2)
                    if mqttconf.get('haintegration'):
                        st = t.split('/')
                        print(st)
                        hatopic = 'homeassistant/device_automation/rtl433_%s_%s/action_%s_%s/config' % (st[2], st[3], st[4], length)
                        hamessage = '''{
                          "automation_type": "trigger","type": "action",
                          "subtype": "%s", "payload": "%s","topic": "%s_%s",
                          "device": {
                            "identifiers": ["rtl433_%s_%s"], 
                            "name": "%s_%s", "model": "%s"
                            }
                          }''' % (st[4] + '_' + length, st[4] + '_' + length, t, length, st[2], st[3], st[2], st[3], st[2])
                        mqttSend(hatopic, hamessage, qos=2)
                    buff.pop(t)
        await asyncio.sleep(checkPeriod)

async def mqttStatus():
    if not dryrun:
        while True:
            l.debug('Sending uptime message')
            mqttSend('/rtl433/uptime', ts() - startts)
            await asyncio.sleep(mqttconf.get('statperiod'))

async def main():
    await asyncio.gather(rtl433(), buffChecker(), mqttStatus())

if __name__ == "__main__":
    mqttSend('/rtl433/laststart', startts)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())

# vim: syntax=python tabstop=4 expandtab shiftwidth=4 softtabstop=4

#!/usr/bin/env python
# -*- coding: utf-8 -*-
import paho.mqtt.client as mqtt #import library
import time

MQTT_BROKER = "localhost"   #Ip du broker donc la c'est localhost pour faire l'arbitre
MQTT_TOPIC = "test_channel" #this is the name of topic

global messageReceived #
messageReceived=False

# callback called when client receives a CONNACK response
def on_connect(client, userdata, flags, rc):
    if rc==0:
        client.subscribe(MQTT_TOPIC)
        print("subscribe to {}".format(MQTT_TOPIC))
    else:
        syslog.syslog("bad connection {}".format(rc))

# callback called when a PUBLISH message is received
def on_message(client, userdata, msg):
    print(msg.topic+" "+str(msg.payload.decode("utf-8")))
    
    global messageReceived
    messageReceived=True

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER)
client.loop_forever()# use this line if you don't want to write any further code. It blocks the code forever to check for data

"""
client.loop_start()  #use this line if you want to write any more code here
delay=0.001
counter=120/delay #2min
while messageReceived==False and counter>0:
    time.sleep(delay)
client.loop_stop()    
"""
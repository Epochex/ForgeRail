import argparse, json, os, time
from pathlib import Path
from kafka import KafkaConsumer, KafkaProducer
from kafka.structs import OffsetAndMetadata, TopicPartition
from ledger import Ledger
p=argparse.ArgumentParser(); p.add_argument('--mode', choices=['produce','consume'], required=True); p.add_argument('--topic',required=True); p.add_argument('--group'); p.add_argument('--db'); p.add_argument('--crash',action='store_true'); p.add_argument('--value-offset',type=int,default=0); args=p.parse_args()
if args.mode=='produce':
    producer=KafkaProducer(bootstrap_servers='redpanda:9092', value_serializer=lambda x:json.dumps(x).encode(), acks='all')
    for n in range(12): producer.send(args.topic, {'id':f'event-{n}', 'value':n}).get(timeout=30)
    producer.flush(); print(json.dumps({'produced':12})); producer.close()
else:
    ledger=Ledger(args.db)
    consumer=KafkaConsumer(args.topic, bootstrap_servers='redpanda:9092', group_id=args.group, enable_auto_commit=False, auto_offset_reset='earliest', consumer_timeout_ms=12000, value_deserializer=lambda x:json.loads(x.decode()))
    delivered=duplicates=0
    for message in consumer:
        event=dict(message.value, value=message.value['value']+args.value_offset)
        fresh=ledger.apply(event,message.offset,message.partition); delivered+=1; duplicates+=int(not fresh)
        if args.crash:
            print(json.dumps({'crash_after_durable_write':True,'summary':ledger.summary()}),flush=True); os._exit(23)
        consumer.commit({TopicPartition(message.topic,message.partition):OffsetAndMetadata(message.offset+1,'',-1)})
    print(json.dumps({'delivered':delivered,'duplicates':duplicates,'summary':ledger.summary()})); consumer.close()

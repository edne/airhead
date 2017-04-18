#!/usr/bin/env python3
import os
from uuid import uuid4
import json
import atexit
import logging

from queue import Queue
from aiohttp import web

import mutagen
from mutagen.oggvorbis import OggVorbis
from mutagen.mp3 import MP3
from mutagen.flac import FLAC

from airhead.config import get_config
from airhead.playlist import Playlist
from airhead.transmitter import Transmitter
from airhead.transcoder import Transcoder

conf = get_config()

transmitter_queue = Playlist()
transmitter = Transmitter(conf, transmitter_queue)
transmitter.daemon = True
transmitter.start()
atexit.register(transmitter.join)

transcoder_queue = Queue()
transcoder = Transcoder(conf, transcoder_queue)
transcoder.daemon = True
transcoder.start()
atexit.register(transcoder.join)


def get_tags(uuid):
    path = os.path.join(conf.get('PATHS', 'Tracks'), uuid + '.json')
    with open(path) as fp:
        track = json.load(fp)
        track['uuid'] = uuid
        return track


def grep_tags(path, query):
    with open(path) as fp:
        track = json.load(fp)

        return any(query.lower() in value.lower()
                   for value in track.values())


def get_tracks(query=None):
    tracks = []
    base = os.path.join(conf.get('PATHS', 'Tracks'))

    try:
        for f in os.listdir(base):
            if f.endswith('.json'):

                path = os.path.join(base, f)
                uuid = os.path.splitext(f)[0]

                if query:
                    if grep_tags(path, query):
                        tracks.append(uuid)

                else:
                    tracks.append(uuid)

    except FileNotFoundError:
        pass

    return tracks


async def info(request):
    info = {
        'name': conf.get('WEB', 'Name'),
        'greet_message': conf.get('WEB', 'GreetMessage'),
        'stream_url': 'http://{}:{}/{}'.format(
            conf.get('TRANSMITTER', 'Host'),
            conf.get('TRANSMITTER', 'Port'),
            conf.get('TRANSMITTER', 'Mount'))
    }
    return web.json_response(info)


async def tracks(request):
    q = request.query.get('q', None)

    tracks = [get_tags(uuid)
              for uuid in get_tracks(q)]

    return web.json_response({'total': len(tracks),
                              'items': tracks})


def is_valid_audio_file(path):
    with open(path, 'rb') as stream:
        f = mutagen.File(stream)
        return (isinstance(f, OggVorbis)
                or isinstance(f, MP3)
                or isinstance(f, FLAC))


async def upload(request):
    uuid = str(uuid4())
    path = os.path.join(conf.get('PATHS', 'Upload'), uuid)

    reader = await request.multipart()
    data = await reader.next()

    with open(path, 'wb') as f:
        while True:
            chunk = await data.read_chunk()
            if not chunk:
                break
            f.write(chunk)

    if not is_valid_audio_file(path):
        os.remove(path)
        raise Exception('Invalid audio file.')

    transcoder_queue.put(uuid)
    return web.json_response({'uuid': 202})


async def queue(request):
    tracks = [get_tags(uuid)
              for uuid in transmitter_queue.queue]

    return web.json_response({'total': len(tracks),
                              'items': tracks})


def enqueue(request):
    uuid = request.match_info['uuid']
    transmitter_queue.put(str(uuid))
    return web.Response()


def dequeue(request):
    uuid = request.match_info['uuid']
    transmitter_queue.dequeue(str(uuid))
    return web.Response()


async def now_playing(request):
    uuid = transmitter.now_playing
    track = get_tags(uuid) if uuid else {}

    return web.json_response({'track': track})


async def index(request):
    return web.FileResponse(os.path.join(conf.get('PATHS', 'Resources'),
                                         'index.html'))


if __name__ == '__main__':
    if conf.getboolean('GENERAL', 'Debug'):
        logging.basicConfig(level=logging.DEBUG)

    app = web.Application()

    app.router.add_get('/api/info', info)

    app.router.add_get('/api/tracks', tracks)
    app.router.add_post('/api/tracks', upload)

    app.router.add_get('/api/queue', queue)
    app.router.add_put('/api/queue/{uuid}', enqueue)
    app.router.add_delete('/api/queue/{uuid}', dequeue)
    app.router.add_get('/api/queue/current', now_playing)

    app.router.add_get('/', index)
    app.router.add_static('/', conf.get('PATHS', 'Resources'))

    web.run_app(app, host='0.0.0.0', port=8080)

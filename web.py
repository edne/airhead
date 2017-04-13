#!/usr/bin/env python3
import os.path
from uuid import uuid4
import json
import atexit
import logging

from queue import Queue
from aiohttp import web

from airhead.config import get_config
from airhead.transmitter import Transmitter
from airhead.transcoder import Transcoder

conf = get_config()

transmitter_queue = Queue()
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


def paginate(tracks, start=0, limit=10):
    end = start + limit

    try:
        return tracks[start:end]
    except IndexError:
        return tracks[start:]


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
    start = int(request.query.get('start', '0'))
    limit = int(request.query.get('limit', '10'))
    q = request.query.get('q', None)

    tracks = [get_tags(uuid)
              for uuid in get_tracks(q)]

    return web.json_response({'total': len(tracks),
                              'items': paginate(tracks, start, limit)})


class AudioFileRequired:
    field_flags = ('required', )

    DEFAULT_MESSAGE = "Invalid audio file."

    def __init__(self, message=None):
        self.message = (message if message
                        else self.DEFAULT_MESSAGE)


async def upload(request):
    uuid = str(uuid4())
    path = os.path.join(conf.get('PATHS', 'Upload'), uuid)

    reader = await request.multipart()
    data = await reader.next()

    # TODO: validate input
    with open(path, 'wb') as f:
        while True:
            chunk = await data.read_chunk()
            if not chunk:
                break
            f.write(chunk)

    transcoder_queue.put(uuid)
    return web.json_response({'uuid': 202})


async def queue(request):
    start = int(request.query.get('start', '0'))
    limit = int(request.query.get('limit', '10'))

    tracks = [get_tags(uuid)
              for uuid in transmitter_queue.queue]

    return web.json_response({'total': len(tracks),
                              'items': paginate(tracks, start, limit)})


def enqueue(request):
    uuid = request.match_info['uuid']
    transmitter_queue.put(str(uuid))
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
    app.router.add_get('/api/queue/current', now_playing)

    app.router.add_get('/', index)
    app.router.add_static('/', conf.get('PATHS', 'Resources'))

    web.run_app(app, host='0.0.0.0', port=8080)

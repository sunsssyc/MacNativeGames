"""Anthropic models on Google Cloud Vertex AI over REST (publishers/anthropic/models/<model>:rawPredict), with the
harness tools run in this process: for Macs without Claude Code or Codex. Standard library only.

The access token comes from `gcloud auth print-access-token` (the gcloud sign-in on this Mac); the project from
assistant.json vertex.project, ANTHROPIC_VERTEX_PROJECT_ID / GOOGLE_CLOUD_PROJECT, or `gcloud config get-value project`.
Nothing here enables APIs, creates resources or changes Google Cloud settings: a model that is not enabled for the
project is reported as an error."""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

from .backends import BackendError, find_binary
from .harness import Harness, ToolError, image_block

ANTHROPIC_VERSION = 'vertex-2023-10-16'   # the request body field Vertex AI requires
MAX_TURNS = 8
MAX_TOKENS = 16000
_cache = {}


def gcloud(config):
    v = config.get('vertex') or {}
    return find_binary('gcloud', v.get('gcloud'), ('/opt/homebrew/bin/gcloud', '/usr/local/bin/gcloud',
                                                  '~/google-cloud-sdk/bin/gcloud', '/opt/homebrew/share/google-cloud-sdk/bin/gcloud'))


def project_and_region(config):
    v = config.get('vertex') or {}
    project = v.get('project') or os.environ.get('ANTHROPIC_VERTEX_PROJECT_ID') or os.environ.get('GOOGLE_CLOUD_PROJECT')
    if not project:
        binary = gcloud(config)
        if binary:
            if ('project', binary) not in _cache:
                try:
                    r = subprocess.run([binary, 'config', 'get-value', 'project'], capture_output=True, text=True, timeout=30)
                    _cache[('project', binary)] = r.stdout.strip() if r.returncode == 0 else ''
                except (OSError, subprocess.TimeoutExpired):
                    _cache[('project', binary)] = ''
            project = _cache[('project', binary)]
    region = v.get('region') or os.environ.get('CLOUD_ML_REGION') or 'global'
    return project or None, region


def endpoint(project, region, model):
    host = 'aiplatform.googleapis.com' if region == 'global' else f'{region}-aiplatform.googleapis.com'
    return (f'https://{host}/v1/projects/{project}/locations/{region}/publishers/anthropic/models/{model}:rawPredict')


class VertexREST:
    name = 'vertex'
    title = 'Vertex AI'

    def __init__(self, config):
        self.config = config
        self.settings = config.get('vertex') or {}

    def available(self):
        if not gcloud(self.config):
            return False, 'gcloud is not installed'
        project, _ = project_and_region(self.config)
        if not project:
            return False, 'no Google Cloud project (assistant.json vertex.project or gcloud config set project)'
        return True, ''

    def token(self):
        binary = gcloud(self.config)
        cached = _cache.get(('token', binary))
        if cached and time.monotonic() - cached[1] < 40 * 60:
            return cached[0]
        try:
            r = subprocess.run([binary, 'auth', 'print-access-token'], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise BackendError(f'gcloud auth print-access-token did not run: {e}') from None
        token = r.stdout.strip()
        if r.returncode != 0 or not token:
            raise BackendError('gcloud has no usable sign-in (gcloud auth login): ' + (r.stderr.strip().splitlines() or [''])[-1][:200])
        _cache[('token', binary)] = (token, time.monotonic())
        return token

    def post(self, model, body, timeout):
        project, region = project_and_region(self.config)
        request = urllib.request.Request(endpoint(project, region, model), data=json.dumps(body).encode(), method='POST',
                                         headers={'Authorization': f'Bearer {self.token()}',
                                                  'Content-Type': 'application/json; charset=utf-8'})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read())
                message = (detail.get('error') or {}).get('message') if isinstance(detail.get('error'), dict) else detail
            except ValueError:
                message = e.reason
            if e.code == 404:
                message = f'model {model} is not available to project {project} in {region} ({message})'
            raise BackendError(f'Vertex AI HTTP {e.code}: {str(message)[:300]}') from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise BackendError(f'Vertex AI request failed: {e}') from None

    def run(self, system, prompt, ctx):
        harness = Harness(self.config, ctx.romfs, ctx.save_root, ctx.allow_screenshot)
        tools = [{'name': s['name'], 'description': s['description'], 'input_schema': s['inputSchema']}
                 for s in harness.tool_specs()]
        model = self.settings.get('model') or 'claude-opus-5-5'
        fallback = self.settings.get('fallback_model')
        messages = [{'role': 'user', 'content': prompt}]
        deadline = time.monotonic() + ctx.timeout
        calls = 0
        for turn in range(MAX_TURNS):
            ctx.check()
            remaining = deadline - time.monotonic()
            if remaining <= 5:
                raise BackendError(f'Vertex AI did not answer within {ctx.timeout:.0f} s')
            body = {'anthropic_version': ANTHROPIC_VERSION, 'max_tokens': MAX_TOKENS, 'system': system,
                    'messages': messages, 'tools': tools}
            if self.settings.get('effort'):
                body['output_config'] = {'effort': self.settings['effort']}
            response = self.post(model, body, min(remaining, 180))
            stop = response.get('stop_reason')
            if stop == 'refusal':
                # no server-side fallback on Vertex AI: send the same conversation once to the fallback model
                if fallback and model != fallback:
                    model = fallback
                    continue
                raise BackendError('the model declined this request')
            content = response.get('content') or []
            messages.append({'role': 'assistant', 'content': content})   # unchanged: thinking blocks stay valid
            if stop == 'tool_use':
                results = []
                for block in content:
                    if block.get('type') != 'tool_use':
                        continue
                    calls += 1
                    try:
                        text, image = harness.call(block.get('name'), block.get('input') or {})
                        result = [{'type': 'text', 'text': text}]
                        if image:
                            mime, data = image_block(image)
                            result.append({'type': 'image', 'source': {'type': 'base64', 'media_type': mime, 'data': data}})
                        results.append({'type': 'tool_result', 'tool_use_id': block['id'], 'content': result})
                    except ToolError as e:
                        results.append({'type': 'tool_result', 'tool_use_id': block['id'], 'content': str(e), 'is_error': True})
                    except Exception as e:
                        results.append({'type': 'tool_result', 'tool_use_id': block['id'],
                                        'content': f'{type(e).__name__}: {e}', 'is_error': True})
                messages.append({'role': 'user', 'content': results})   # all results of this turn in one message
                continue
            text = ''.join(b.get('text', '') for b in content if b.get('type') == 'text').strip()
            if not text:
                raise BackendError(f'Vertex AI returned no text (stop reason {stop})')
            return {'text': text, 'model': model, 'turns': turn + 1, 'tool_calls': calls}
        raise BackendError(f'no answer after {MAX_TURNS} tool rounds')

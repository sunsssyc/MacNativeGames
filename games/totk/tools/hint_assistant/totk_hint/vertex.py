"""Anthropic models on Google Cloud Vertex AI over REST (publishers/anthropic/models/<model>:streamRawPredict), with the
harness tools run in this process by the assistant's own agent loop (agent.py): for Macs without Claude Code or Codex.
Standard library only.

The access token comes from a credentials file when there is one (assistant.json vertex.credentials, else
GOOGLE_APPLICATION_CREDENTIALS): a service account key (signed with the system's openssl, the key passed through a
pipe, never written anywhere) or an authorized-user file (gcloud auth application-default login). Without one it is
`gcloud auth print-access-token`, the gcloud sign-in on this Mac. The project is assistant.json vertex.project,
ANTHROPIC_VERTEX_PROJECT_ID / GOOGLE_CLOUD_PROJECT, the credentials file's project, or `gcloud config get-value project`.
Nothing here enables APIs, creates resources or changes Google Cloud settings (gcloud's own sign-in is never touched): a
model that is not enabled for the project is reported as an error."""
import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .backends import BackendError, find_binary

TOKEN_URL = 'https://oauth2.googleapis.com/token'
SCOPE = 'https://www.googleapis.com/auth/cloud-platform'
OPENSSL = '/usr/bin/openssl'

ANTHROPIC_VERSION = 'vertex-2023-10-16'   # the request body field Vertex AI requires
_cache = {}


def gcloud(config):
    v = config.get('vertex') or {}
    return find_binary('gcloud', v.get('gcloud'), ('/opt/homebrew/bin/gcloud', '/usr/local/bin/gcloud',
                                                  '~/google-cloud-sdk/bin/gcloud', '/opt/homebrew/share/google-cloud-sdk/bin/gcloud'))


def credentials_file(config):
    """The Google credentials file to sign in with, or None (then gcloud)."""
    path = (config.get('vertex') or {}).get('credentials') or os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    return Path(path).expanduser() if path else None


def credentials(config):
    """The credentials file's contents, or None; BackendError when it is named but unusable."""
    path = credentials_file(config)
    if not path:
        return None
    try:
        info = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise BackendError(f'the Google credentials file {path} cannot be read: {type(e).__name__}') from None
    kind = info.get('type') if isinstance(info, dict) else None
    if kind == 'service_account' and info.get('private_key') and info.get('client_email'):
        return info
    if kind == 'authorized_user' and info.get('refresh_token') and info.get('client_id'):
        return info
    raise BackendError(f'{path}: not a service account key or an authorized-user credentials file (type {kind})')


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _post_form(url, fields, timeout=30):
    request = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method='POST',
                                     headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read())
            message = detail.get('error_description') or detail.get('error') or detail
        except ValueError:
            message = e.reason
        raise BackendError(f'Google sign-in refused (HTTP {e.code}): {str(message)[:200]}') from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise BackendError(f'Google sign-in failed: {e}') from None


def token_from(info, now=None):
    """(access token, seconds it lasts) for a service account key or an authorized-user file."""
    url = info.get('token_uri') or TOKEN_URL
    if info['type'] == 'authorized_user':
        reply = _post_form(url, {'grant_type': 'refresh_token', 'client_id': info['client_id'],
                                 'client_secret': info.get('client_secret', ''), 'refresh_token': info['refresh_token']})
    else:
        now = int(now or time.time())
        header = {'alg': 'RS256', 'typ': 'JWT'}
        if info.get('private_key_id'):
            header['kid'] = info['private_key_id']
        claims = {'iss': info['client_email'], 'sub': info['client_email'], 'scope': SCOPE, 'aud': url,
                  'iat': now, 'exp': now + 3600}
        signing = f'{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}'
        read, write = os.pipe()   # the key reaches openssl through a pipe: it is never written to a file
        try:
            os.write(write, info['private_key'].encode())
            os.close(write)
            write = None
            signed = subprocess.run([OPENSSL, 'dgst', '-sha256', '-sign', f'/dev/fd/{read}'], input=signing.encode(),
                                    capture_output=True, pass_fds=(read,), timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise BackendError(f'openssl did not sign the sign-in request: {e}') from None
        finally:
            os.close(read)
            if write is not None:
                os.close(write)
        if signed.returncode != 0 or not signed.stdout:
            raise BackendError('openssl could not sign with the service account key: '
                               + (signed.stderr.decode(errors='replace').strip().splitlines() or [''])[-1][:200])
        reply = _post_form(url, {'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                                 'assertion': f'{signing}.{_b64(signed.stdout)}'})
    if not reply.get('access_token'):
        raise BackendError('Google sign-in returned no access token')
    return reply['access_token'], int(reply.get('expires_in') or 3600)


def project_and_region(config):
    v = config.get('vertex') or {}
    project = v.get('project') or os.environ.get('ANTHROPIC_VERTEX_PROJECT_ID') or os.environ.get('GOOGLE_CLOUD_PROJECT')
    if not project:
        try:
            info = credentials(config)
        except BackendError:
            info = None
        project = (info or {}).get('project_id') or (info or {}).get('quota_project_id')
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
        try:
            signed_in = credentials(self.config) is not None or gcloud(self.config)
        except BackendError as e:
            return False, str(e)
        if not signed_in:
            return False, 'no Google sign-in (assistant.json vertex.credentials, or gcloud installed and signed in)'
        project, _ = project_and_region(self.config)
        if not project:
            return False, 'no Google Cloud project (assistant.json vertex.project or gcloud config set project)'
        return True, ''

    def token(self):
        info = credentials(self.config)
        if info is not None:
            key = ('token', str(credentials_file(self.config)))
            cached = _cache.get(key)
            if cached and time.monotonic() < cached[1]:
                return cached[0]
            token, lasts = token_from(info)
            _cache[key] = (token, time.monotonic() + max(60, lasts - 300))
            return token
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

    def run(self, system, prompt, ctx):
        """The assistant's agent loop (agent.py) with this model: tool calls, plan and research, streamed answers."""
        from .agent import VertexProvider, run
        try:
            return run(VertexProvider(self), system, prompt, ctx, self.config, self.settings)
        except BackendError as e:
            raise BackendError(f'Vertex AI: {e}') from None

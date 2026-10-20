#!/usr/bin/env python3
"""Classify redacted gitleaks history offline; never print source secrets or PII."""
import argparse
import base64
import hashlib
import hmac
import json
from pathlib import Path
import re
import subprocess
import time


def decode(value):
    return json.loads(base64.urlsafe_b64decode(value+'='*(-len(value)%4)))


def triage(findings, current):
    result=[]
    cache={}
    jwt_pattern=re.compile(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')
    for finding in findings:
        commit, file = finding['Commit'], finding['File']
        if not re.fullmatch(r'[a-f0-9]{40}',commit) or Path(file).is_absolute() or '..' in Path(file).parts:
            raise ValueError('Unsafe history reference')
        key=(commit,file)
        if key not in cache:
            cache[key]=subprocess.run(['git','show',commit+':'+file],check=True,capture_output=True).stdout.decode('utf-8',errors='replace').splitlines()
        lines=cache[key]
        source='\n'.join(lines[max(0,finding['StartLine']-1):finding['EndLine']])
        candidates=jwt_pattern.findall(source)
        token=candidates[0] if len(candidates)==1 else None
        record={'file':file,'commit':commit,'line':finding['StartLine'],'rule':finding['RuleID'],
                'current_configuration_match':False,'disposition':'manual_review_required'}
        if token:
            record['identifier']=hashlib.sha256(token.encode()).hexdigest()[:16]
            try:
                header,payload=map(decode,token.split('.')[:2])
                role=payload.get('role')
                record['role']=role if role in ('anon','authenticated','service_role') else 'other'
                expiration=payload.get('exp')
                record['expired']=isinstance(expiration,(int,float)) and expiration<time.time()
                record['has_expiration']=isinstance(expiration,(int,float))
                record['current_configuration_match']=any(hmac.compare_digest(token,v) for v in current.values() if len(v)>=12)
                secret=current.get('SUPABASE_JWT_SECRET')
                if secret and header.get('alg')=='HS256':
                    signed='.'.join(token.split('.')[:2]).encode()
                    signature=base64.urlsafe_b64encode(hmac.new(secret.encode(),signed,hashlib.sha256).digest()).decode().rstrip('=')
                    record['signed_by_current_jwt_key']=hmac.compare_digest(signature,token.split('.')[2])
                if record['expired']:
                    record['disposition']='expired_jwt'
                elif file.startswith('tests/') and len(base64.urlsafe_b64decode(token.split('.')[2]+'='*(-len(token.split('.')[2])%4)))!=32 and header.get('alg')=='HS256':
                    record['disposition']='invalid_test_jwt'
                elif record['current_configuration_match'] or record.get('signed_by_current_jwt_key'):
                    record['disposition']='current_credential_requires_rotation_review'
                else:
                    record['disposition']='historical_jwt_external_revocation_unknown'
            except (ValueError,TypeError,KeyError,AttributeError):
                record['disposition']='malformed_or_test_jwt'
        else:
            record['identifier']=hashlib.sha256(source.encode()).hexdigest()[:16]
            record['current_configuration_match']=any(v in source for v in current.values() if len(v)>=12)
            if record['current_configuration_match']:
                record['disposition']='current_credential_requires_rotation_review'
            elif finding['RuleID']=='curl-auth-header' and re.search(r'\$\{?[A-Z][A-Z_]+',source):
                record['disposition']='shell_variable_example'
            elif file.startswith('tests/'):
                record['disposition']='test_fixture_requires_review'
        result.append(record)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',required=True)
    parser.add_argument('--current-env',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    current={}
    allowed={'SUPABASE_SERVICE_ROLE_KEY','SUPABASE_ANON_KEY','SUPABASE_JWT_SECRET','SMTP_PASSWORD','OPENWA_MASTER_KEY','INVITE_HMAC_SECRET','LINK_GATEWAY_API_KEY'}
    if args.current_env:
        for line in args.current_env.read_text().splitlines():
            key,separator,value=line.partition('=')
            if separator and key in allowed:
                current[key]=value.strip().strip('"').strip("'")
    result=triage(json.loads(Path(args.report).read_text()),current)
    from collections import Counter
    output={'method':'offline source inspection and equality/HMAC checks against current local configuration; no credential sent to any service',
            'configuration_keys_checked':sorted(current),
            'findings':len(result),'unique_identifiers':len({r['identifier'] for r in result}),
            'dispositions':dict(Counter(r['disposition'] for r in result)),
            'current_configuration_matches':sum(r['current_configuration_match'] for r in result),
            'current_jwt_signing_key_matches':sum(r.get('signed_by_current_jwt_key',False) for r in result),
            'items':result}
    args.output.write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps({k:v for k,v in output.items() if k!='items'}))


if __name__=='__main__':
    main()

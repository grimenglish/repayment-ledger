import getpass
import hashlib
import secrets
password = getpass.getpass('새 로그인 비밀번호 (12자 이상): ')
if len(password) < 12:
    raise SystemExit('12자 이상의 비밀번호를 사용해주세요.')
if password != getpass.getpass('한 번 더 입력: '):
    raise SystemExit('입력한 비밀번호가 다릅니다.')
salt = secrets.token_hex(32)
value = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600_000).hex()
print('[login]\nsalt = "' + salt + '"\npassword_hash = "' + value + '"')

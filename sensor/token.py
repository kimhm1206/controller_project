from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
import requests
import base64

def get_token(email="root@telofarm.com", password="tf170221!"):
    # 1. 공개키 받아오기 (base64-encoded PEM 문자열)
    r = requests.get("https://datadam.telofarm.com/api/auth", timeout=10)
    b64_pem = r.json()["publicKey"].strip()

    # 2. Base64 디코딩 → PEM 문자열 복원
    pem_str = base64.b64decode(b64_pem).decode("utf-8")
    pem_bytes = pem_str.encode("utf-8")

    # print("🔓 PEM 복원 성공")

    # 3. PEM 키 로딩
    public_key = serialization.load_pem_public_key(pem_bytes)

    # 4. 암호화
    encrypted = public_key.encrypt(
        password.encode("utf-8"),
        padding.PKCS1v15()
    )
    encrypted_b64 = base64.b64encode(encrypted).decode("utf-8")

    # 5. 토큰 요청
    url = f"https://datadam.telofarm.com/api/auth?email={email}&secret={encrypted_b64}"
    res = requests.post(url, json={})
    token = res.headers.get("Set-Cookie")
    # print("✅ 토큰 발급 성공")

    return token

"""API トークンを、このパソコンのこのユーザーでしか読めない形にして持つ。

Windows の DPAPI (CryptProtectData) をそのまま使う。鍵はサインインした
アカウントに紐づくので、フォルダごとコピーされても別のユーザー・別のパソコンでは
復号できない。追加のライブラリは要らず、同梱の Python でそのまま動く。

暗号化そのものが目的ではない。設定済みのフォルダをうっかり人に渡してしまったとき、
中身の鍵が読めない状態にしておくのが目的。
"""
import base64
import ctypes
import ctypes.wintypes

CRYPTPROTECT_UI_FORBIDDEN = 0x0001


class _Blob(ctypes.Structure):
    _fields_ = [('cbData', ctypes.wintypes.DWORD),
                ('pbData', ctypes.POINTER(ctypes.c_char))]


_crypt32  = ctypes.WinDLL('crypt32', use_last_error=True)
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

_BLOB_P = ctypes.POINTER(_Blob)

_crypt32.CryptProtectData.argtypes = [_BLOB_P, ctypes.c_wchar_p, _BLOB_P,
                                      ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.wintypes.DWORD, _BLOB_P]
_crypt32.CryptProtectData.restype = ctypes.wintypes.BOOL

_crypt32.CryptUnprotectData.argtypes = [_BLOB_P, ctypes.POINTER(ctypes.c_wchar_p), _BLOB_P,
                                        ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.wintypes.DWORD, _BLOB_P]
_crypt32.CryptUnprotectData.restype = ctypes.wintypes.BOOL

_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
_kernel32.LocalFree.restype = ctypes.c_void_p


def _to_blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
    """入力用の BLOB を作る。

    バッファ本体も一緒に返すこと。呼び出し側が持っていないと、
    API へ渡す前に回収されて中身が化ける。
    """
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _take(blob: _Blob) -> bytes:
    """出力 BLOB から中身を取り出し、API が確保した領域を返す。"""
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        _kernel32.LocalFree(blob.pbData)


def encrypt(text: str) -> str:
    """このユーザーだけが読める形にして、base64 の文字列で返す。"""
    if not text:
        return ''
    src, _keep = _to_blob(text.encode('utf-8'))
    out = _Blob()
    ok = _crypt32.CryptProtectData(ctypes.byref(src), None, None, None, None,
                                   CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
    if not ok:
        raise OSError(ctypes.get_last_error(), 'CryptProtectData が失敗しました')
    return base64.b64encode(_take(out)).decode('ascii')


def decrypt(encoded: str) -> str:
    """encrypt が返した文字列を元に戻す。

    別のユーザー・別のパソコンで作られたものは復号できない。それが狙いなので、
    失敗は異常ではなく「持ち主が違う」という結果として扱う。
    """
    if not encoded:
        return ''
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as e:
        raise ValueError('保存された接続情報の形が壊れています') from e

    src, _keep = _to_blob(raw)
    out = _Blob()
    ok = _crypt32.CryptUnprotectData(ctypes.byref(src), None, None, None, None,
                                     CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
    if not ok:
        raise ValueError('このパソコン（このユーザー）では読めない接続情報です')
    return _take(out).decode('utf-8')

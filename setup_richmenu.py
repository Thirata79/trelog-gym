"""
LINE リッチメニューをAPI経由で設定するスクリプト
使い方: python setup_richmenu.py
環境変数 LINE_CHANNEL_ACCESS_TOKEN が必要
"""
import os
import json
import requests

LINE_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
BASE_URL = "https://api.line.me/v2/bot"

def create_richmenu():
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json"
    }

    richmenu_data = {
        "size": {"width": 2500, "height": 1686},
        "selected": True,
        "name": "トレログ メニュー",
        "chatBarText": "メニュー",
        "areas": [
            {
                "bounds": {"x": 0, "y": 0, "width": 1250, "height": 843},
                "action": {"type": "message", "text": "/記録"}
            },
            {
                "bounds": {"x": 1250, "y": 0, "width": 1250, "height": 843},
                "action": {"type": "message", "text": "/送信"}
            },
            {
                "bounds": {"x": 0, "y": 843, "width": 1250, "height": 843},
                "action": {"type": "message", "text": "/準備"}
            },
            {
                "bounds": {"x": 1250, "y": 843, "width": 1250, "height": 843},
                "action": {"type": "message", "text": "/レポート"}
            }
        ]
    }

    # 1. リッチメニューを作成
    print("リッチメニューを作成中...")
    res = requests.post(f"{BASE_URL}/richmenu", headers=headers, json=richmenu_data)
    if res.status_code != 200:
        print(f"エラー: {res.status_code} {res.text}")
        return
    richmenu_id = res.json()["richMenuId"]
    print(f"リッチメニューID: {richmenu_id}")

    # 2. 画像をアップロード
    print("画像をアップロード中...")
    img_headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "image/png"
    }
    with open(os.path.join(os.path.dirname(__file__), "richmenu.png"), "rb") as f:
        res = requests.post(
            f"https://api-data.line.me/v2/bot/richmenu/{richmenu_id}/content",
            headers=img_headers,
            data=f.read()
        )
    if res.status_code != 200:
        print(f"画像アップロードエラー: {res.status_code} {res.text}")
        return
    print("画像アップロード完了")

    # 3. デフォルトリッチメニューに設定
    print("デフォルトに設定中...")
    res = requests.post(
        f"{BASE_URL}/user/all/richmenu/{richmenu_id}",
        headers={"Authorization": f"Bearer {LINE_TOKEN}"}
    )
    if res.status_code != 200:
        print(f"デフォルト設定エラー: {res.status_code} {res.text}")
        return
    print("デフォルトリッチメニュー設定完了！")

if __name__ == "__main__":
    if not LINE_TOKEN:
        print("LINE_CHANNEL_ACCESS_TOKEN 環境変数を設定してください。")
    else:
        create_richmenu()

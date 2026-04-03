import os
import json
import re
import tempfile
import requests
from flask import Flask, request, jsonify
from openai import OpenAI
import gspread
from datetime import datetime

app = Flask(__name__)

# ---------- クライアント設定 ----------
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
LINE_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")

# ---------- トレーナーID ----------
TRAINER_IDS = ["Uf3f9b02171a5548eb9ff140738ac2255"]

# ---------- セッション一時保存（メモリ内） ----------
sessions = {}

# 記録待ちのクライアント名 { userId: clientName }
recording_for = {}

# ========== LINE送信ヘルパー ==========
def push_message(to, messages):
    headers = {"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"}
    requests.post(LINE_PUSH_URL, headers=headers, json={"to": to, "messages": messages})

def reply_message(reply_token, messages):
    headers = {"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"}
    requests.post(LINE_REPLY_URL, headers=headers, json={"replyToken": reply_token, "messages": messages})

# ========== Google Sheets共通クライアント ==========
def get_sheets_client():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS", "")
    if not creds_json:
        raise Exception("GOOGLE_CREDENTIALS not set")
    try:
        creds_data = json.loads(creds_json)
    except json.JSONDecodeError:
        fixed = re.sub(
            r'("private_key"\s*:\s*")(.*?)(")',
            lambda m: m.group(1) + m.group(2).replace('\n', '\\n') + m.group(3),
            creds_json, flags=re.DOTALL
        )
        creds_data = json.loads(fixed)
    if "private_key" in creds_data:
        creds_data["private_key"] = creds_data["private_key"].replace("\\n", "\n")
    return gspread.service_account_from_dict(creds_data)

# ========== エクササイズ英日マッピング（部位別・包括的） ==========
EN_TO_JA = {
    # ===== 脚・臀部 (Legs & Glutes) =====
    # -- スクワット系 --
    "Back Squat": "バックスクワット", "Front Squat": "フロントスクワット",
    "Goblet Squat": "ゴブレットスクワット", "Plate Squat": "プレートスクワット",
    "Box Squat": "ボックススクワット", "Split Squat": "スプリットスクワット",
    "Bulgarian Split Squat": "ブルガリアンスプリットスクワット",
    "Crossover Squat": "クロスオーバースクワット", "Curtsy Squat": "カーツィースクワット",
    "Jefferson Squat": "ジェファーソンスクワット", "Zercher Squat": "ゼルチャースクワット",
    "Overhead Squat": "オーバーヘッドスクワット", "Pause Squat": "ポーズスクワット",
    "Smith Machine Squat": "スミスマシンスクワット", "Hack Squat": "ハックスクワット",
    "Sissy Squat": "シシースクワット", "Pistol Squat": "ピストルスクワット",
    "Air Squat": "エアスクワット", "Sumo Squat": "スモウスクワット",
    # -- デッドリフト系 --
    "Deadlift": "デッドリフト", "Sumo Deadlift": "スモウデッドリフト",
    "Trap Bar Deadlift": "トラップバーデッドリフト",
    "RDL": "RDL", "Romanian Deadlift": "ルーマニアンデッドリフト",
    "Single Leg RDL": "シングルレッグRDL", "Stiff Leg Deadlift": "スティフレッグデッドリフト",
    "Deficit Deadlift": "デフィシットデッドリフト", "Block Pull": "ブロックプル",
    "Kettle Bell RDL": "ケトルベルRDL",
    # -- ランジ系 --
    "Lunge": "ランジ", "Walking Lunge": "ウォーキングランジ",
    "Reverse Lunge": "リバースランジ", "Lateral Lunge": "ラテラルランジ",
    "Curtsy Lunge": "カーツィーランジ", "DB Lunge": "ダンベルランジ",
    "BB Lunge": "バーベルランジ",
    # -- ヒップ・臀部 --
    "Hip Thrust": "ヒップスラスト", "BB Hip Thrust": "バーベルヒップスラスト",
    "Single Leg Hip Thrust": "シングルレッグヒップスラスト",
    "BB Glute Bridge": "BBグルートブリッジ", "Glute Bridge": "グルートブリッジ",
    "Hip Abduction": "ヒップアブダクション", "Machine Adduction": "マシンアダクション",
    "Cable Kickback": "ケーブルキックバック", "Glute Kickback": "グルートキックバック",
    "Cable Pull Through": "ケーブルプルスルー", "Donkey Kick": "ドンキーキック",
    "Fire Hydrant": "ファイヤーハイドラント", "Clamshell": "クラムシェル",
    "Frog Pump": "フロッグパンプ", "Banded Walk": "バンドウォーク",
    # -- マシン脚 --
    "Leg Press": "レッグプレス", "Leg Curl": "レッグカール",
    "Leg Extension": "レッグエクステンション", "Seated Leg Curl": "シーテッドレッグカール",
    "Laying Leg Curl": "ライイングレッグカール", "Pendulum Squat": "ペンデュラムスクワット",
    "V Squat": "Vスクワット", "Belt Squat": "ベルトスクワット",
    # -- ハムストリング --
    "Laying Curls": "レイイングカール", "Seated Curls": "シーテッドカール",
    "Nordic Curl": "ノルディックカール", "Glute Ham Raise": "グルートハムレイズ",
    "Good Morning": "グッドモーニング", "Seated Good Morning": "シーテッドグッドモーニング",
    # -- カーフ --
    "Calf Raise": "カーフレイズ", "Standing Calf Raise": "スタンディングカーフレイズ",
    "Seated Calf Raise": "シーテッドカーフレイズ", "Donkey Calf Raise": "ドンキーカーフレイズ",
    "Single Leg Calf Raise": "シングルレッグカーフレイズ",
    # -- ステップ・ジャンプ --
    "Step Up": "ステップアップ", "Box Jump": "ボックスジャンプ",
    "Jump Squat": "ジャンプスクワット", "Depth Jump": "デプスジャンプ",
    "Broad Jump": "ブロードジャンプ", "Split Jump": "スプリットジャンプ",

    # ===== 胸 (Chest) =====
    # -- プレス系 --
    "Bench Press": "ベンチプレス", "DB Bench Press": "ダンベルベンチプレス",
    "Incline Bench": "インクラインベンチ", "Incline Bench Press": "インクラインベンチプレス",
    "Incline DB Press": "インクラインダンベルプレス",
    "Decline Bench": "デクラインベンチ", "Decline DB Press": "デクラインダンベルプレス",
    "Close Grip Bench Press": "クローズグリップベンチプレス",
    "Floor Press": "フロアプレス", "DB Floor Press": "ダンベルフロアプレス",
    "Machine Chest Press": "マシンチェストプレス",
    "Smith Machine Bench Press": "スミスマシンベンチプレス",
    # -- フライ系 --
    "Chest Flies": "チェストフライ", "DB Flye": "ダンベルフライ",
    "Incline DB Flye": "インクラインダンベルフライ",
    "Cable Fly": "ケーブルフライ", "Cable Crossover": "ケーブルクロスオーバー",
    "Low Cable Fly": "ロウケーブルフライ", "High Cable Fly": "ハイケーブルフライ",
    "Pec Deck": "ペックデック", "Machine Fly": "マシンフライ",
    # -- プッシュアップ系 --
    "Pushups": "プッシュアップ", "Push Up": "プッシュアップ",
    "Incline Pushups": "インクラインプッシュアップ",
    "Decline Pushups": "デクラインプッシュアップ",
    "Diamond Pushups": "ダイヤモンドプッシュアップ",
    "Wide Pushups": "ワイドプッシュアップ",
    # -- ディップ --
    "Dip": "ディップ", "Chest Dip": "チェストディップ",
    "Weighted Dip": "ウェイテッドディップ", "Machine Dip": "マシンディップ",

    # ===== 背中 (Back) =====
    # -- プル系（垂直） --
    "Pull Up": "プルアップ", "Chin Up": "チンアップ",
    "Wide Grip Pull Up": "ワイドグリッププルアップ",
    "Weighted Pull Up": "ウェイテッドプルアップ",
    "Lat Pulldowns": "ラットプルダウン", "Lat Pulldown": "ラットプルダウン",
    "Close Grip Pulldown": "クローズグリッププルダウン",
    "Reverse Grip Pulldown": "リバースグリッププルダウン",
    "Straight Arm Pulldown": "ストレートアームプルダウン",
    "Assisted Pull Up": "アシステッドプルアップ",
    "Chain Pullups": "チェーンプルアップ",
    # -- ロウ系（水平） --
    "BB Rows": "バーベルロウ", "Barbell Row": "バーベルロウ",
    "DB Rows": "ダンベルロウ", "DB Row": "ダンベルロウ",
    "Pendlay Row": "ペンドレイロウ", "T-Bar Row": "Tバーロウ",
    "Chest Supported Rows": "チェストサポーテッドロウ",
    "Chest Supported Row": "チェストサポーテッドロウ",
    "Cable Row": "ケーブルロウ", "Seated Row": "シーテッドロウ",
    "Seated Cable Row": "シーテッドケーブルロウ",
    "Single Arm DB Row": "ワンアームダンベルロウ",
    "Meadows Row": "メドウズロウ", "Seal Row": "シールロウ",
    "Inverted Row": "インバーテッドロウ", "TRX Row": "TRXロウ",
    "High Row": "ハイロウ", "Machine Row": "マシンロウ",
    "Gorilla Row": "ゴリラロウ",
    # -- その他背中 --
    "Face Pull": "フェイスプル", "Band Pull Apart": "バンドプルアパート",
    "Band pull-apart": "バンドプルアパート",
    "Hyperextension": "ハイパーエクステンション",
    "Back Extension": "バックエクステンション",
    "Reverse Hyper": "リバースハイパー",
    "Rack Pull": "ラックプル",
    "Shrug": "シュラッグ", "BB Shrug": "バーベルシュラッグ",
    "DB Shrug": "ダンベルシュラッグ", "Trap Bar Shrug": "トラップバーシュラッグ",

    # ===== 肩 (Shoulders) =====
    # -- プレス系 --
    "BB Shoulder Press": "BBショルダープレス", "Overhead Press": "オーバーヘッドプレス",
    "Military Press": "ミリタリープレス",
    "DB Shoulder Press": "DBショルダープレス", "Seated DB Press": "シーテッドダンベルプレス",
    "Arnold Press": "アーノルドプレス",
    "Machine Shoulder Press": "マシンショルダープレス",
    "Smith Machine OHP": "スミスマシンOHP",
    "Push Press": "プッシュプレス", "Z Press": "Zプレス",
    "Landmine Press": "ランドマインプレス",
    # -- レイズ系 --
    "Side Raises": "サイドレイズ", "Lateral Raise": "ラテラルレイズ",
    "DB Lateral Raise": "ダンベルサイドレイズ",
    "Cable Lateral Raise": "ケーブルサイドレイズ",
    "Machine Lateral Raise": "マシンサイドレイズ",
    "Front Raises": "フロントレイズ", "Front Raise": "フロントレイズ",
    "Cable Front Raise": "ケーブルフロントレイズ",
    "Rear Delt Flyes": "リアデルトフライ", "Rear Delt Fly": "リアデルトフライ",
    "Reverse Fly": "リバースフライ", "Reverse Pec Deck": "リバースペックデック",
    "Cable Reverse Fly": "ケーブルリバースフライ",
    "Upright Rows": "アップライトロウ", "Upright Row": "アップライトロウ",
    "Cable Upright Row": "ケーブルアップライトロウ",
    "Lu Raise": "ルーレイズ", "Y Raise": "Yレイズ",
    "Prone Y Raise": "プローンYレイズ",

    # ===== 腕 (Arms) =====
    # -- 二頭筋 --
    "BB Curl": "BBカール", "Barbell Curl": "バーベルカール",
    "EZ Bar Curl": "EZバーカール", "DB Curl": "ダンベルカール",
    "Hammer Curl": "ハンマーカール", "Preacher Curl": "プリーチャーカール",
    "Incline DB Curl": "インクラインダンベルカール",
    "Concentration Curl": "コンセントレーションカール",
    "Spider Curl": "スパイダーカール", "Cable Curl": "ケーブルカール",
    "Bayesian Curl": "ベイジアンカール",
    "Drag Curl": "ドラッグカール", "Zottman Curl": "ゾットマンカール",
    "21s": "21s（トゥエンティワンズ）",
    "Machine Curl": "マシンカール",
    # -- 三頭筋 --
    "Tricep Pushdown": "トライセプスプッシュダウン",
    "Rope Pushdown": "ロープブッシュダウン",
    "V-Bar Pushdown": "Vバープッシュダウン",
    "Overhead Tricep Extension": "オーバーヘッドトライセプスエクステンション",
    "Cable Overhead Extension": "ケーブルオーバーヘッドエクステンション",
    "Skull Crusher": "スカルクラッシャー", "Lying Tricep Extension": "ライイングトライセプスエクステンション",
    "DB Kickback": "ダンベルキックバック", "Tricep Kickback": "トライセプスキックバック",
    "Close Grip Bench": "クローズグリップベンチ",
    "Diamond Push Up": "ダイヤモンドプッシュアップ",
    "Tricep Dip": "トライセプスディップ",
    "JM Press": "JMプレス",
    # -- 前腕 --
    "Wrist Curl": "リストカール", "Reverse Wrist Curl": "リバースリストカール",
    "Farmer Walk": "ファーマーウォーク", "Farmers Walk": "ファーマーウォーク",
    "Dead Hang": "デッドハング", "Plate Pinch": "プレートピンチ",
    "Fat Grip Hold": "ファットグリップホールド",

    # ===== コア・腹筋 (Core & Abs) =====
    "Plank": "プランク", "Side Plank": "サイドプランク",
    "RKC Plank": "RKCプランク",
    "Crunch": "クランチ", "Cable Crunch": "ケーブルクランチ",
    "Reverse Crunch": "リバースクランチ", "Bicycle Crunch": "バイシクルクランチ",
    "Sit Up": "シットアップ", "V-Up": "Vアップ",
    "Leg Raise": "レッグレイズ", "Hanging Leg Raise": "ハンギングレッグレイズ",
    "Lying Leg Raise": "ライイングレッグレイズ",
    "Knee Raise": "ニーレイズ", "Hanging Knee Raise": "ハンギングニーレイズ",
    "Ab Wheel": "アブローラー", "Ab Rollout": "アブローラー",
    "Pallof Press": "パロフプレス", "Cable Pallof Press": "ケーブルパロフプレス",
    "Russian Twist": "ロシアンツイスト",
    "Woodchop": "ウッドチョップ", "Cable Woodchop": "ケーブルウッドチョップ",
    "Dead Bug": "デッドバグ", "Bird Dog": "バードドッグ",
    "Mountain Climber": "マウンテンクライマー",
    "Toe Touch": "トータッチ", "Flutter Kick": "フラッターキック",
    "Hollow Body Hold": "ホロウボディホールド",
    "Dragon Flag": "ドラゴンフラッグ",
    "Ab Crunch Machine": "アブクランチマシン",
    "Decline Sit Up": "デクラインシットアップ",
    "Copenhagen Plank": "コペンハーゲンプランク",
    "Suitcase Carry": "スーツケースキャリー",

    # ===== ケトルベル (Kettlebell) =====
    "K-Bell Swing": "ケトルベルスウィング", "Kettlebell Swing": "ケトルベルスウィング",
    "KB Snatch": "ケトルベルスナッチ", "Kettlebell Snatch": "ケトルベルスナッチ",
    "KB Clean": "ケトルベルクリーン", "KB Clean and Press": "ケトルベルクリーン＆プレス",
    "KB Goblet Squat": "ケトルベルゴブレットスクワット",
    "Turkish Get Up": "ターキッシュゲットアップ", "TGU": "ターキッシュゲットアップ",
    "KB Windmill": "ケトルベルウィンドミル",
    "KB Halo": "ケトルベルハロー",
    "KB Row": "ケトルベルロウ",

    # ===== オリンピックリフト・パワー系 =====
    "Power Clean": "パワークリーン", "Clean": "クリーン",
    "Clean and Jerk": "クリーン＆ジャーク", "Hang Clean": "ハングクリーン",
    "Power Snatch": "パワースナッチ", "Snatch": "スナッチ",
    "Hang Snatch": "ハングスナッチ",
    "Clean Pull": "クリーンプル", "Snatch Pull": "スナッチプル",
    "Push Jerk": "プッシュジャーク", "Split Jerk": "スプリットジャーク",
    "Thruster": "スラスター", "Cluster": "クラスター",
    "Muscle Up": "マッスルアップ", "Bar Muscle Up": "バーマッスルアップ",
    "Ring Muscle Up": "リングマッスルアップ",

    # ===== 有酸素・コンディショニング (Cardio & Conditioning) =====
    "Treadmill": "トレッドミル", "Incline Walk": "インクラインウォーク",
    "Stair Climber": "ステアクライマー", "StairMaster": "ステアマスター",
    "Elliptical": "エリプティカル", "Stationary Bike": "エアロバイク",
    "Assault Bike": "アサルトバイク", "Spin Bike": "スピンバイク",
    "Rowing Machine": "ローイングマシン", "Rower": "ローイングマシン",
    "Ski Erg": "スキーエルグ", "Bike Erg": "バイクエルグ",
    "Battle Rope": "バトルロープ", "Jump Rope": "縄跳び",
    "Double Unders": "ダブルアンダー（二重跳び）",
    "Sled Push": "スレッドプッシュ", "Sled Pull": "スレッドプル",
    "Prowler Push": "プラウラープッシュ",
    "Burpee": "バーピー", "Burpees": "バーピー",
    "Man Maker": "マンメーカー",
    "HIIT": "HIIT", "Tabata": "タバタ", "EMOM": "EMOM", "AMRAP": "AMRAP",
    "Circuit": "サーキット",

    # ===== ストレッチ・モビリティ (Mobility & Recovery) =====
    "Foam Roll": "フォームローラー", "Foam Rolling": "フォームローリング",
    "Lacrosse Ball": "ラクロスボール",
    "Hip Flexor Stretch": "ヒップフレクサーストレッチ",
    "Pigeon Stretch": "ピジョンストレッチ",
    "Couch Stretch": "カウチストレッチ",
    "90/90 Stretch": "90/90ストレッチ",
    "World's Greatest Stretch": "ワールズグレイテストストレッチ",
    "Cat Cow": "キャットカウ", "Child's Pose": "チャイルドポーズ",
    "Downward Dog": "ダウンワードドッグ",
    "Wall Slide": "ウォールスライド",
    "Banded Distraction": "バンドディストラクション",
    "Shoulder Dislocate": "ショルダーディスロケート",
    "Thoracic Extension": "胸椎エクステンション",
    "Ankle Mobility": "アンクルモビリティ",
    "Hip Circle": "ヒップサークル",
    "Leg Swing": "レッグスウィング",
    "Arm Circle": "アームサークル",
    "Band Pull Apart": "バンドプルアパート",
}

_vocab_cache = {"terms_ja": None, "terms_en": None, "updated": None}

def get_vocabulary():
    """用語リスト＋エクササイズライブラリから用語を取得（10分キャッシュ）"""
    now = datetime.now()
    if _vocab_cache["terms_ja"] and _vocab_cache["updated"] and (now - _vocab_cache["updated"]).seconds < 600:
        return _vocab_cache["terms_ja"], _vocab_cache["terms_en"]

    terms_ja = []
    terms_en = []
    try:
        client = get_sheets_client()
        wb = client.open_by_key(SHEET_ID)

        # 用語リスト（日本語専門用語）
        try:
            vocab_sheet = wb.worksheet("用語リスト")
            vocab_rows = vocab_sheet.get_all_values()
            for row in vocab_rows[1:]:
                term = row[1] if len(row) > 1 else ""
                if term:
                    terms_ja.append(term)
        except Exception as e:
            print(f"[用語リスト読込] {e}", flush=True)

        # エクササイズライブラリ（英語エクササイズ名）
        try:
            ex_sheet = wb.worksheet("エクササイズライブラリ")
            ex_rows = ex_sheet.get_all_values()
            for row in ex_rows[2:]:
                for cell in row:
                    if cell and cell.strip():
                        terms_en.append(cell.strip())
        except Exception as e:
            print(f"[エクササイズライブラリ読込] {e}", flush=True)

        # 英日マッピングでカタカナ変換
        for en in terms_en:
            ja = EN_TO_JA.get(en)
            if ja:
                terms_ja.append(ja)

        _vocab_cache["terms_ja"] = terms_ja
        _vocab_cache["terms_en"] = terms_en
        _vocab_cache["updated"] = now
        print(f"[用語] 日本語{len(terms_ja)}件 / 英語{len(terms_en)}件", flush=True)
    except Exception as e:
        print(f"[用語読込エラー] {e}", flush=True)

    return terms_ja or [], terms_en or []

# ========== クライアントマスターからLINE ID取得 ==========
def normalize_name(name):
    """名前の表記揺れを吸収（スペース全角半角除去）"""
    return name.replace(" ", "").replace("\u3000", "").strip()

def get_client_line_id(client_name):
    """クライアントマスターシートからクライアント名でLINE IDを検索
    シート構造: A=ID, B=クライアント名, C=LINE UserID, D=目標, E=注意事項,
                F=体重, G=身長, H=生年月日
    """
    try:
        client = get_sheets_client()
        sheet = client.open_by_key(SHEET_ID).worksheet("クライアントマスター")
        rows = sheet.get_all_values()
        target = normalize_name(client_name)

        # rows[0]=タイトル行, rows[1]=ヘッダー行, rows[2:]以降=データ
        for row in rows[2:]:
            name = row[1] if len(row) > 1 else ""       # B列: クライアント名
            line_id = row[2] if len(row) > 2 else ""     # C列: LINE UserID（本人）
            if normalize_name(name) == target and line_id:
                return line_id
        return None
    except Exception as e:
        print(f"[クライアントマスターエラー] {e}", flush=True)
        return None

def get_client_info(client_name):
    """クライアントマスターから詳細情報を取得"""
    try:
        client = get_sheets_client()
        sheet = client.open_by_key(SHEET_ID).worksheet("クライアントマスター")
        rows = sheet.get_all_values()
        target = normalize_name(client_name)

        for row in rows[2:]:
            name = row[1] if len(row) > 1 else ""
            if normalize_name(name) == target:
                return {
                    "name": name,
                    "line_id": row[2] if len(row) > 2 else "",
                    "goal": row[3] if len(row) > 3 else "",
                    "caution": row[4] if len(row) > 4 else "",
                    "weight": row[5] if len(row) > 5 else "",
                    "height": row[6] if len(row) > 6 else "",
                    "birthday": row[7] if len(row) > 7 else "",
                }
        return None
    except Exception as e:
        print(f"[クライアント情報取得エラー] {e}", flush=True)
        return None

# ========== リッチメニュー制御 ==========
def link_richmenu_to_user(user_id):
    """デフォルトリッチメニューを取得してユーザーにリンク"""
    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    # デフォルトリッチメニューIDを取得
    res = requests.get(f"https://api.line.me/v2/bot/user/all/richmenu", headers=headers)
    if res.status_code == 200:
        richmenu_id = res.json().get("richMenuId")
        if richmenu_id:
            # デフォルトを解除
            requests.delete(f"https://api.line.me/v2/bot/user/all/richmenu", headers=headers)
            # トレーナーに個別リンク
            requests.post(
                f"https://api.line.me/v2/bot/user/{user_id}/richmenu/{richmenu_id}",
                headers=headers
            )
            print(f"[RICHMENU] Linked {richmenu_id} to {user_id}", flush=True)
            return True
    return False

def setup_trainer_richmenu():
    """起動時にデフォルトリッチメニューをトレーナーだけにリンク"""
    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    # デフォルトリッチメニューがあれば取得
    res = requests.get(f"https://api.line.me/v2/bot/user/all/richmenu", headers=headers)
    if res.status_code == 200:
        richmenu_id = res.json().get("richMenuId")
        if richmenu_id:
            # デフォルトを解除
            requests.delete(f"https://api.line.me/v2/bot/user/all/richmenu", headers=headers)
            # 各トレーナーに個別リンク
            for tid in TRAINER_IDS:
                requests.post(
                    f"https://api.line.me/v2/bot/user/{tid}/richmenu/{richmenu_id}",
                    headers=headers
                )
                print(f"[STARTUP] Richmenu linked to trainer {tid}", flush=True)

# 起動時に実行
setup_trainer_richmenu()

# ========== Health Check ==========
@app.route("/health", methods=["GET"])
def health():
    creds = os.environ.get("GOOGLE_CREDENTIALS", "")
    return jsonify({
        "status": "ok",
        "google_credentials_length": len(creds),
        "google_credentials_start": creds[:20] if creds else "EMPTY",
        "google_sheet_id": SHEET_ID[:10] + "..." if SHEET_ID else "NOT SET",
        "line_token_set": bool(LINE_TOKEN),
        "openai_key_set": bool(os.environ.get("OPENAI_API_KEY")),
    })

# ========== Webhook ==========
@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.json
    events = body.get("events", [])

    for event in events:
        event_type = event.get("type")
        user_id = event.get("source", {}).get("userId", "")
        reply_token = event.get("replyToken", "")
        print(f"[EVENT] type={event_type} user={user_id}", flush=True)

        try:
            if event_type == "follow":
                # 友だち追加時: トレーナーにだけリッチメニューをリンク
                if user_id in TRAINER_IDS:
                    link_richmenu_to_user(user_id)
                    print(f"[FOLLOW] Trainer {user_id} - richmenu linked", flush=True)
                else:
                    print(f"[FOLLOW] Client {user_id} - no richmenu", flush=True)
                continue

            # トレーナー以外のメッセージは無視
            if user_id not in TRAINER_IDS:
                print(f"[SKIP] Non-trainer message from {user_id}", flush=True)
                continue

            if event_type == "message":
                msg = event.get("message", {})
                msg_type = msg.get("type")
                print(f"[MESSAGE] type={msg_type}", flush=True)

                if msg_type == "audio":
                    handle_audio(user_id, reply_token, msg.get("id"))
                elif msg_type == "text":
                    handle_text(user_id, reply_token, msg.get("text", ""))

            elif event_type == "postback":
                data = event.get("postback", {}).get("data", "")
                print(f"[POSTBACK] data={data}", flush=True)
                handle_postback(user_id, reply_token, data)

        except Exception as e:
            print(f"[ERROR] {e}", flush=True)
            import traceback
            traceback.print_exc()
            try:
                reply_message(reply_token, [{"type": "text", "text": "処理中にエラーが発生しました。もう一度お試しください。"}])
            except Exception:
                pass

    return jsonify({"status": "ok"})

# ========== 音声処理 ==========
def handle_audio(user_id, reply_token, message_id):
    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    res = requests.get(f"https://api-data.line.me/v2/bot/message/{message_id}/content", headers=headers)

    with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as f:
        f.write(res.content)
        audio_path = f.name

    # 日本語用語をWhisperのpromptに渡して認識精度UP
    try:
        terms_ja, _ = get_vocabulary()
        whisper_prompt = "ジムのトレーニング記録。" + "、".join(terms_ja[:100]) if terms_ja else ""
    except Exception as e:
        print(f"[用語読込スキップ] {e}", flush=True)
        whisper_prompt = ""

    with open(audio_path, "rb") as audio_file:
        transcript = openai_client.audio.transcriptions.create(
            model="whisper-1", file=audio_file, language="ja",
            prompt=whisper_prompt
        )

    # Whisperの変換結果をログに出力
    print(f"[WHISPER RAW] {transcript.text}", flush=True)

    # 事前にクライアントが選択されていればその名前を渡す
    selected_client = recording_for.get(user_id, "")
    parse_and_confirm(user_id, reply_token, transcript.text, selected_client)

# ========== クライアントの言語設定を取得 ==========
def get_client_lang(client_name):
    """クライアントマスターのI列(言語)を取得。未設定ならJA"""
    try:
        gc = get_sheets_client()
        sheet = gc.open_by_key(SHEET_ID).worksheet("クライアントマスター")
        rows = sheet.get_all_values()
        for row in rows[1:]:
            name = row[1] if len(row) > 1 else ""
            if name == client_name:
                lang = row[8] if len(row) > 8 else ""
                return lang.upper().strip() if lang else "JA"
        return "JA"
    except Exception:
        return "JA"

# ========== 音声認識の誤変換を直接テキスト置換 ==========
VOICE_FIX = {
    "ラウンジ": "ランジ",
    "内線": "内旋",
    "外線": "外旋",
    "凱旋": "外旋",
    "回線": "回旋",
    "内戦": "内旋",
    "過信": "外旋",
    "内心": "内旋",
    "外心": "外旋",
    "関節法": "関節包",
    "関節砲": "関節包",
    "大腿師頭": "大腿四頭",
    "大体四頭": "大腿四頭",
    "大体師頭": "大腿四頭",
    "光背筋": "広背筋",
    "高配筋": "広背筋",
    "三頭金": "三頭筋",
    "二頭金": "二頭筋",
    "サンセット": "3セット",
    "ゴセット": "5セット",
    "ゴキロ": "5kg",
    "中回": "10回",
    "デットリフト": "デッドリフト",
    "スクワッド": "スクワット",
    "ラットプル": "ラットプルダウン",
    "ハムスト": "ハムストリング",
    "ローテーターカフス": "ローテーターカフ",
    "権限": "肩甲",
    "腱板": "腱板",
}

def fix_voice_text(text):
    for wrong, correct in VOICE_FIX.items():
        text = text.replace(wrong, correct)
    return text

# ========== GPT解析＋確認（音声・テキスト共通） ==========
def parse_and_confirm(user_id, reply_token, text, selected_client=""):
    # 音声認識の誤変換をPythonで直接修正
    original_text = text
    text = fix_voice_text(text)
    if text != original_text:
        print(f"[VOICE FIX] {original_text} → {text}", flush=True)

    # クライアントの言語設定を取得
    client_lang = get_client_lang(selected_client) if selected_client else "JA"

    # 用語リスト（スペル補正用のみ）
    exercise_hint = ""
    try:
        terms_ja, terms_en = get_vocabulary()
        if terms_ja:
            exercise_hint = f"\n\nSpelling reference only (do NOT add exercises not mentioned by the trainer): {', '.join(terms_ja[:80])}"
    except Exception as e:
        print(f"[用語読込スキップ] {e}", flush=True)

    gpt_res = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant that extracts structured training session notes from a Japanese gym/fitness trainer. "
                    "The trainer may input in Japanese, English, or mixed. "
                    + (
                        "OUTPUT LANGUAGE: ENGLISH. Translate all Japanese input to English. "
                        "Exercise names, Memo, and Next must ALL be in English. "
                        if client_lang == "EN" else
                        "OUTPUT LANGUAGE: JAPANESE. "
                    )
                    + "Always respond with valid JSON only, no markdown, no explanation.\n\n"
                    "FORMAT:\n"
                    "{\n"
                    '  "Client name": "name",\n'
                    '  "Exercises": [\n'
                    '    {"name": "種目名", "sets": 3, "reps": 10, "weight": "60kg", "note": "備考"}\n'
                    "  ],\n"
                    '  "Memo": "observations",\n'
                    '  "Next": "next steps"\n'
                    "}\n\n"
                    "IMPORTANT RULES:\n"
                    "- Only extract what the trainer ACTUALLY said. Do NOT invent or add content.\n"
                    "- Exercises: list ONLY exercises explicitly mentioned. Extract sets/reps/weight separately.\n"
                    "  - sets: number of sets (integer). If not mentioned, omit or null.\n"
                    "  - reps: number of reps (integer or string like '8-12'). If not mentioned, omit or null.\n"
                    "  - weight: weight used (string like '60kg', '20lbs', '自重'). If not mentioned, omit or null.\n"
                    "  - note: per-exercise observation (tempo, ROM, form cue). If none, omit or empty string.\n"
                    "- Cardio exercises: use reps for duration (e.g. '20min'), weight for intensity/speed/incline.\n"
                    "- Memo: summarize ONLY overall observations (fatigue, mood, progress). Do NOT repeat exercise-level notes.\n"
                    "- Next: state ONLY what the trainer said about next steps. If not mentioned, leave empty.\n"
                    "- Fix common voice input errors:\n"
                    "  サンセット→3セット, ゴセット→5セット, 中回→10回, 肘→10, ゴキロ→5kg, etc.\n"
                    "  Interpret numbers in fitness context.\n"
                    "- Fix common VOICE RECOGNITION errors for fitness terms:\n"
                    "  ラウンジ→ランジ, 内線→内旋, 外線→外旋, 凱旋→外旋, 関節法→関節包,\n"
                    "  過信→外旋, 内心→内旋, 外心→外旋, 回線→外旋, 内戦→内旋,\n"
                    "  股関節内線→股関節内旋, 股関節凱旋→股関節外旋, 股関節外線→股関節外旋,\n"
                    "  股関節過信→股関節外旋, 股関節内戦→股関節内旋, 股関節回線→股関節外旋,\n"
                    "  肩関節内線→肩関節内旋, 肩関節凱旋→肩関節外旋, 肩関節外線→肩関節外旋,\n"
                    "  胸椎回線→胸椎回旋, 胸椎凱旋→胸椎回旋, 回旋→回旋,\n"
                    "  デッドリフト→デッドリフト, ベンチプレス→ベンチプレス,\n"
                    "  スクワット→スクワット, ローイング→ローイング,\n"
                    "  ラットプル→ラットプルダウン, ハムスト→ハムストリング,\n"
                    "  大腿師頭→大腿四頭, 三頭→三頭筋, 二頭→二頭筋,\n"
                    "  関節窩→関節窩, 肩甲骨→肩甲骨, 広背筋→広背筋,\n"
                    "  可動域→可動域, ROM→可動域, パーシャル→パーシャル\n"
                    "- IMPORTANT: Include ALL exercises mentioned, even bodyweight exercises, stretches, mobility work.\n"
                    "  Do NOT omit exercises just because they lack sets/reps/weight.\n"
                    "- Preserve the trainer's EXACT observations in Memo. Do NOT simplify or shorten.\n"
                    + (
                        "- Exercise names: use ENGLISH for the name field.\n"
                        "- Memo and Next: write in ENGLISH.\n"
                        if client_lang == "EN" else
                        "- Exercise names: use Japanese (カタカナ) for the name field.\n"
                    )
                    + "- The spelling reference below is ONLY for correcting misspellings. Do NOT use it to add exercises."
                    + exercise_hint
                )
            },
            {"role": "user", "content": text}
        ],
        response_format={"type": "json_object"}
    )

    data = json.loads(gpt_res.choices[0].message.content)

    # 事前にクライアントが選択されていればそちらを優先
    client_name = selected_client if selected_client else data.get("Client name", "")
    exercises = data.get("Exercises", [])
    memo = data.get("Memo", "")
    next_session = data.get("Next", "")

    # エクササイズリストを読みやすい文字列にフォーマット
    is_en = client_lang == "EN"
    menu_lines = []
    for ex in exercises:
        line = "▪ " + ex.get("name", "")
        parts = []
        if ex.get("weight"):
            parts.append(str(ex["weight"]))
        if ex.get("sets") and ex.get("reps"):
            parts.append(f"{ex['sets']}x{ex['reps']}")
        elif ex.get("sets"):
            parts.append(f"{ex['sets']} sets" if is_en else f"{ex['sets']}セット")
        elif ex.get("reps"):
            parts.append(f"{ex['reps']} reps" if is_en else f"{ex['reps']}レップ")
        if parts:
            line += "\n   " + " | ".join(parts)
        if ex.get("note"):
            line += f"\n   ({ex['note']})"
        menu_lines.append(line)

    menu = "\n".join(menu_lines) if menu_lines else data.get("Menu", "")

    sessions[user_id] = {
        "clientName": client_name,
        "menu": menu,
        "exercises": exercises,
        "memo": memo,
        "next": next_session,
        "lang": client_lang
    }

    # 記録待ち状態をクリア
    recording_for.pop(user_id, None)

    if is_en:
        confirm_text = (
            f"Parsed session:\n\n"
            f"Client: {client_name or '(unknown)'}\n"
            f"Menu:\n{menu}\n\n"
            f"Notes: {memo}\n"
            f"Next: {next_session}\n\n"
            "Save this record?"
        )
    else:
        confirm_text = (
            f"以下の内容で解析しました\n\n"
            f"クライアント：{client_name or '（未確認）'}\n"
            f"メニュー：\n{menu}\n\n"
            f"メモ：{memo}\n"
            f"次回：{next_session}\n\n"
            "この内容で記録しますか？"
        )

    reply_message(reply_token, [{
        "type": "text",
        "text": confirm_text,
        "quickReply": {"items": [
            {"type": "action", "action": {"type": "postback", "label": "記録する", "data": "action=記録"}},
            {"type": "action", "action": {"type": "postback", "label": "やり直す", "data": "action=retry"}}
        ]}
    }])

# ========== テキスト処理 ==========
def handle_text(user_id, reply_token, text):
    cmd = text.strip()

    # /記録 → クライアント選択画面
    if cmd in ["/記録", "記録"]:
        handle_record_select(user_id, reply_token)

    # /送信 → 未送信レコード一覧を表示
    elif cmd in ["/送信", "送信"]:
        handle_send_list(user_id, reply_token)

    # /準備 → クライアント選択 → 直近2セッション要約＋サジェスト
    elif cmd in ["/準備", "準備"]:
        handle_prep_select(reply_token)

    # /レポート → 直近サマリー
    elif cmd in ["/レポート", "レポート"]:
        handle_report(reply_token)

    # /体組成 → 体重・体組成記録
    elif cmd in ["/体組成", "体組成"]:
        handle_body_comp_select(user_id, reply_token)

    # /プログラム → プログラム管理
    elif cmd in ["/プログラム", "プログラム"]:
        handle_program_select(reply_token)

    # /履歴 → クライアント別の種目履歴
    elif cmd in ["/履歴", "履歴"]:
        handle_history_select(user_id, reply_token)

    elif len(cmd) > 5:
        # 記録待ちのクライアントがいればそのクライアント名付きで解析
        selected_client = recording_for.get(user_id, "")
        parse_and_confirm(user_id, reply_token, text, selected_client)

# ========== /記録: クライアント選択画面 ==========
def handle_record_select(user_id, reply_token):
    try:
        client = get_sheets_client()
        sheet = client.open_by_key(SHEET_ID).worksheet("クライアントマスター")
        rows = sheet.get_all_values()

        items = []
        for row in rows[2:]:
            name = row[1] if len(row) > 1 else ""
            if name:
                label = name[:20]
                items.append({
                    "type": "action",
                    "action": {
                        "type": "postback",
                        "label": label,
                        "data": f"action=record_for&client={name}"
                    }
                })

        if items:
            reply_message(reply_token, [{
                "type": "text",
                "text": "誰のセッションを記録しますか？",
                "quickReply": {"items": items[:13]}
            }])
        else:
            reply_message(reply_token, [{"type": "text", "text": "クライアントマスターにデータがありません。"}])
    except Exception as e:
        import traceback
        print(f"[記録選択エラー] {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        reply_message(reply_token, [{"type": "text", "text": f"エラー: {type(e).__name__}: {e}"}])

# ========== /送信: 未送信レコード一覧 ==========
def handle_send_list(user_id, reply_token):
    try:
        client = get_sheets_client()
        sheet = client.open_by_key(SHEET_ID).worksheet("セッションログ")
        all_rows = sheet.get_all_values()

        # 未送信レコードを探す（ステータス列 = index 7）
        unsent = []
        for i, row in enumerate(all_rows[1:], start=2):
            status = row[7] if len(row) > 7 else ""
            if status == "未送信":
                name = row[2] if len(row) > 2 else ""
                date = row[1] if len(row) > 1 else ""
                unsent.append({"row": i, "name": name, "date": date})

        if not unsent:
            reply_message(reply_token, [{"type": "text", "text": "未送信のレコードはありません。"}])
            return

        items = []
        for rec in unsent[-10:]:
            label = f"{rec['name']} {rec['date']}"
            if len(label) > 20:
                label = label[:20]
            items.append({
                "type": "action",
                "action": {
                    "type": "postback",
                    "label": label,
                    "data": f"action=send_row&row={rec['row']}"
                }
            })

        reply_message(reply_token, [{
            "type": "text",
            "text": f"未送信のレコードが{len(unsent)}件あります。\n送信するクライアントを選んでください。",
            "quickReply": {"items": items}
        }])
    except Exception as e:
        print(f"[送信一覧エラー] {e}", flush=True)
        import traceback
        traceback.print_exc()
        reply_message(reply_token, [{"type": "text", "text": "データ取得中にエラーが発生しました。"}])

# ========== /準備: クライアント選択画面 ==========
def handle_prep_select(reply_token):
    try:
        client = get_sheets_client()
        sheet = client.open_by_key(SHEET_ID).worksheet("クライアントマスター")
        rows = sheet.get_all_values()

        items = []
        for row in rows[2:]:
            name = row[1] if len(row) > 1 else ""
            if name:
                label = name[:20]
                items.append({
                    "type": "action",
                    "action": {
                        "type": "postback",
                        "label": label,
                        "data": f"action=prep&client={name}"
                    }
                })

        if items:
            reply_message(reply_token, [{
                "type": "text",
                "text": "次回準備をするクライアントを選んでください。",
                "quickReply": {"items": items[:13]}
            }])
        else:
            reply_message(reply_token, [{"type": "text", "text": "クライアントマスターにデータがありません。"}])
    except Exception as e:
        print(f"[準備選択エラー] {e}", flush=True)
        reply_message(reply_token, [{"type": "text", "text": "データ取得中にエラーが発生しました。"}])

# ========== /準備: 直近2セッション要約＋サジェスト ==========
def handle_next_prep(reply_token, client_name):
    try:
        print(f"[準備] クライアント={client_name}", flush=True)
        client = get_sheets_client()
        sheet = client.open_by_key(SHEET_ID).worksheet("セッションログ")
        all_rows = sheet.get_all_values()

        target = normalize_name(client_name)
        client_rows = []
        for row in all_rows[1:]:
            name = row[2] if len(row) > 2 else ""
            if normalize_name(name) == target:
                client_rows.append(row)

        print(f"[準備] {client_name}の記録数={len(client_rows)}", flush=True)

        if not client_rows:
            reply_message(reply_token, [{"type": "text", "text": f"{client_name}さんの記録がまだありません。"}])
            return

        # 直近2件を取得
        recent = client_rows[-2:]
        session_text = ""
        for row in recent:
            date = row[1] if len(row) > 1 else ""
            menu = row[3] if len(row) > 3 else ""
            memo = row[4] if len(row) > 4 else ""
            trainer = row[5] if len(row) > 5 else ""
            next_note = row[6] if len(row) > 6 else ""
            session_text += f"日付:{date} メニュー:{menu} メモ:{memo} 所見:{trainer} 申し送り:{next_note}\n"

        # クライアント情報を取得
        client_info_data = get_client_info(client_name)
        client_info = ""
        if client_info_data:
            client_info = (
                f"目標:{client_info_data.get('goal', '')} "
                f"注意事項:{client_info_data.get('caution', '')} "
                f"体重:{client_info_data.get('weight', '')} "
                f"身長:{client_info_data.get('height', '')}"
            )

        # 体組成履歴も取得（直近3件）
        body_comp_text = ""
        try:
            bc_sheet = client.open_by_key(SHEET_ID).worksheet("体組成ログ")
            bc_rows = bc_sheet.get_all_values()
            bc_client = [r for r in bc_rows[1:] if normalize_name(r[1] if len(r) > 1 else "") == target]
            for row in bc_client[-3:]:
                date = row[0] if len(row) > 0 else ""
                weight = row[2] if len(row) > 2 else ""
                bf = row[3] if len(row) > 3 else ""
                muscle = row[4] if len(row) > 4 else ""
                body_comp_text += f"  {date}: 体重{weight}kg 体脂肪{bf}% 筋肉量{muscle}kg\n"
        except Exception:
            pass

        # GPTで要約＋サジェスト
        prompt = (
            f"以下はジムのクライアント「{client_name}」の情報と直近セッション記録です。\n\n"
            f"【クライアント情報】{client_info}\n\n"
        )
        if body_comp_text:
            prompt += f"【体組成推移】\n{body_comp_text}\n"
        prompt += (
            f"【直近セッション】\n{session_text}\n"
            f"上記を踏まえて、以下を簡潔に日本語で答えてください：\n"
            f"1. 直近のトレーニング要約（3行以内）\n"
            f"2. 成長ポイント・改善点\n"
            f"3. 次回セッションで取り組むべきこと（具体的な提案）"
        )

        gpt_res = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "あなたはジムトレーナーのアシスタントです。簡潔で実用的なアドバイスをしてください。"},
                {"role": "user", "content": prompt}
            ]
        )

        summary = gpt_res.choices[0].message.content
        reply_message(reply_token, [{
            "type": "text",
            "text": f"【{client_name}さん 次回準備】\n\n{summary}"
        }])
    except Exception as e:
        print(f"[準備エラー] {e}", flush=True)
        import traceback
        traceback.print_exc()
        reply_message(reply_token, [{"type": "text", "text": "データ取得中にエラーが発生しました。"}])

# ========== /レポート: 直近サマリー ==========
def handle_report(reply_token):
    try:
        client = get_sheets_client()
        sheet = client.open_by_key(SHEET_ID).worksheet("セッションログ")
        all_rows = sheet.get_all_values()
        total = len(all_rows) - 1

        if total > 0:
            latest = all_rows[-1]
            date = latest[1] if len(latest) > 1 else ""
            name = latest[2] if len(latest) > 2 else ""
            menu = latest[3] if len(latest) > 3 else ""
            reply_message(reply_token, [{"type": "text", "text": (
                f"レポート\n\n"
                f"総セッション数：{total}件\n"
                f"最新記録：{date}\n"
                f"クライアント：{name}\n"
                f"内容：{menu}\n\n"
                f"詳細はスプレッドシートを確認してください。"
            )}])
        else:
            reply_message(reply_token, [{"type": "text", "text": "まだ記録がありません。"}])
    except Exception as e:
        print(f"[レポートエラー] {e}", flush=True)
        reply_message(reply_token, [{"type": "text", "text": "データ取得中にエラーが発生しました。"}])

# ========== /履歴: クライアント選択 ==========
def handle_history_select(user_id, reply_token):
    try:
        client = get_sheets_client()
        sheet = client.open_by_key(SHEET_ID).worksheet("クライアントマスター")
        rows = sheet.get_all_values()

        items = []
        for row in rows[2:]:
            name = row[1] if len(row) > 1 else ""
            if name:
                items.append({
                    "type": "action",
                    "action": {
                        "type": "postback",
                        "label": name[:20],
                        "data": f"action=history_for&client={name}"
                    }
                })

        if items:
            reply_message(reply_token, [{
                "type": "text",
                "text": "誰の種目別履歴を確認しますか？",
                "quickReply": {"items": items[:13]}
            }])
        else:
            reply_message(reply_token, [{"type": "text", "text": "クライアントマスターにデータがありません。"}])
    except Exception as e:
        print(f"[履歴選択エラー] {e}", flush=True)
        reply_message(reply_token, [{"type": "text", "text": "データ取得中にエラーが発生しました。"}])

# ========== /履歴: 種目別サマリー表示 ==========
def handle_history_view(user_id, reply_token, client_name):
    try:
        client = get_sheets_client()
        workbook = client.open_by_key(SHEET_ID)

        sheet_name = f"種目_{client_name}"
        try:
            ex_sheet = workbook.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            reply_message(reply_token, [{"type": "text", "text": f"{client_name}さんの種目別履歴はまだありません。セッションを記録すると自動作成されます。"}])
            return

        rows = ex_sheet.get_all_values()

        # 種目ごとにまとめる
        exercises = {}
        for row in rows[1:]:
            if len(row) >= 5:
                date = row[0][:10]
                name = row[1]
                weight = row[2]
                sets = row[3]
                reps = row[4]
                note = row[5] if len(row) > 5 else ""

                if name not in exercises:
                    exercises[name] = []
                entry = f"  {date}: "
                parts = []
                if weight:
                    parts.append(weight)
                if sets and reps:
                    parts.append(f"{sets}x{reps}")
                elif sets:
                    parts.append(f"{sets}セット")
                elif reps:
                    parts.append(f"{reps}レップ")
                entry += " ".join(parts) if parts else "記録あり"
                if note:
                    entry += f" ({note})"
                exercises[name].append(entry)

        if not exercises:
            reply_message(reply_token, [{"type": "text", "text": f"{client_name}さんの種目別履歴はまだありません。"}])
            return

        # 種目別にフォーマット
        lines = [f"📋 {client_name}さんの種目別履歴\n"]
        for ex_name, records in exercises.items():
            lines.append(f"▸ {ex_name}")
            for r in records[-5:]:  # 直近5回分まで
                lines.append(r)
            lines.append("")

        text = "\n".join(lines)
        # LINEメッセージは5000文字まで
        if len(text) > 4900:
            text = text[:4900] + "\n...（一部省略）"

        reply_message(reply_token, [{"type": "text", "text": text}])

    except Exception as e:
        print(f"[履歴表示エラー] {e}", flush=True)
        reply_message(reply_token, [{"type": "text", "text": "履歴取得中にエラーが発生しました。"}])

# ========== /体組成: クライアント選択 ==========
def handle_body_comp_select(user_id, reply_token):
    try:
        gc = get_sheets_client()
        sheet = gc.open_by_key(SHEET_ID).worksheet("クライアントマスター")
        rows = sheet.get_all_values()

        items = []
        for row in rows[2:]:
            name = row[1] if len(row) > 1 else ""
            if name:
                items.append({
                    "type": "action",
                    "action": {
                        "type": "postback",
                        "label": name[:20],
                        "data": f"action=bodycomp_for&client={name}"
                    }
                })

        if items:
            reply_message(reply_token, [{
                "type": "text",
                "text": "体組成を記録するクライアントを選んでください。",
                "quickReply": {"items": items[:13]}
            }])
        else:
            reply_message(reply_token, [{"type": "text", "text": "クライアントマスターにデータがありません。"}])
    except Exception as e:
        print(f"[体組成選択エラー] {e}", flush=True)
        reply_message(reply_token, [{"type": "text", "text": "データ取得中にエラーが発生しました。"}])

# ========== /プログラム: クライアント選択 ==========
def handle_program_select(reply_token):
    try:
        gc = get_sheets_client()
        sheet = gc.open_by_key(SHEET_ID).worksheet("クライアントマスター")
        rows = sheet.get_all_values()

        items = []
        for row in rows[2:]:
            name = row[1] if len(row) > 1 else ""
            if name:
                items.append({
                    "type": "action",
                    "action": {
                        "type": "postback",
                        "label": name[:20],
                        "data": f"action=program_view&client={name}"
                    }
                })

        if items:
            reply_message(reply_token, [{
                "type": "text",
                "text": "プログラムを確認するクライアントを選んでください。",
                "quickReply": {"items": items[:13]}
            }])
        else:
            reply_message(reply_token, [{"type": "text", "text": "クライアントマスターにデータがありません。"}])
    except Exception as e:
        print(f"[プログラム選択エラー] {e}", flush=True)
        reply_message(reply_token, [{"type": "text", "text": "データ取得中にエラーが発生しました。"}])

# ========== ポストバック処理 ==========
def handle_postback(user_id, reply_token, data):
    params = dict(p.split("=", 1) for p in data.split("&") if "=" in p)
    action = params.get("action", "")

    # ---------- 記録対象のクライアントを選択 ----------
    if action == "record_for":
        client_name = params.get("client", "")
        recording_for[user_id] = client_name
        reply_message(reply_token, [{"type": "text", "text": f"{client_name}さんですね。\nトレーニング内容を音声またはテキストで教えてください。"}])
        return

    # ---------- 記録する ----------
    if action == "記録":
        session = sessions.get(user_id)
        if not session:
            reply_message(reply_token, [{"type": "text", "text": "セッションデータが見つかりません。もう一度送ってください。"}])
            return

        try:
            write_to_sheets(session)
        except Exception as e:
            import traceback
            print(f"Sheets error: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()

        reply_message(reply_token, [{
            "type": "text",
            "text": "記録しました！\n\nクライアントに送信しますか？",
            "quickReply": {"items": [
                {"type": "action", "action": {"type": "postback", "label": "送信する", "data": "action=送信"}},
                {"type": "action", "action": {"type": "postback", "label": "スキップ", "data": "action=スキップ"}}
            ]}
        }])

    # ---------- 記録直後の送信（メモリから） ----------
    elif action == "送信":
        session = sessions.get(user_id)
        if not session:
            reply_message(reply_token, [{"type": "text", "text": "セッションデータが見つかりません。"}])
            return

        client_name = session.get("clientName", "")
        client_line_id = get_client_line_id(client_name)

        if client_line_id:
            lang = get_client_lang(client_name)
            menu = session.get('menu', '')
            memo = session.get('memo', '')
            next_s = session.get('next', '')
            if lang == "EN":
                msg_text = (
                    f"━━━━━━━━━━━━━━\n"
                    f"  Training Record\n"
                    f"━━━━━━━━━━━━━━\n\n"
                    f"{menu}\n\n"
                    + (f"📝 Notes:\n{memo}\n\n" if memo else "")
                    + (f"📌 Next Session:\n{next_s}\n\n" if next_s else "")
                    + f"Great work today! 💪"
                )
            else:
                msg_text = (
                    f"━━━━━━━━━━━━━━\n"
                    f"  トレーニング記録\n"
                    f"━━━━━━━━━━━━━━\n\n"
                    f"{menu}\n\n"
                    + (f"📝 メモ:\n{memo}\n\n" if memo else "")
                    + (f"📌 次回:\n{next_s}\n\n" if next_s else "")
                    + f"お疲れ様でした！💪"
                )
            push_message(client_line_id, [{"type": "text", "text": msg_text}])
            try:
                update_send_status_by_name(client_name)
            except Exception as e:
                print(f"[ステータス更新エラー] {e}", flush=True)
            reply_message(reply_token, [{"type": "text", "text": f"{client_name}さんに送信しました！"}])
            sessions.pop(user_id, None)
        else:
            reply_message(reply_token, [{"type": "text", "text": f"「{client_name}」のLINE IDがクライアントマスターに登録されていません。"}])

    # ---------- 未送信一覧から選択して送信（スプレッドシートから） ----------
    elif action == "send_row":
        row_num = int(params.get("row", 0))
        if row_num < 2:
            reply_message(reply_token, [{"type": "text", "text": "無効なレコードです。"}])
            return

        try:
            gc = get_sheets_client()
            sheet = gc.open_by_key(SHEET_ID).worksheet("セッションログ")
            row = sheet.row_values(row_num)

            client_name = row[2] if len(row) > 2 else ""
            menu = row[3] if len(row) > 3 else ""
            memo = row[4] if len(row) > 4 else ""
            next_note = row[6] if len(row) > 6 else ""

            client_line_id = get_client_line_id(client_name)

            if client_line_id:
                push_message(client_line_id, [{"type": "text", "text": (
                    f"【トレーニング記録】\n"
                    f"メニュー：{menu}\n"
                    f"メモ：{memo}\n"
                    f"次回：{next_note}\n\n"
                    f"お疲れ様でした！"
                )}])
                sheet.update_cell(row_num, 8, "送信済み")
                reply_message(reply_token, [{"type": "text", "text": f"{client_name}さんに送信しました！"}])
            else:
                reply_message(reply_token, [{"type": "text", "text": f"「{client_name}」のLINE IDがクライアントマスターに登録されていません。"}])
        except Exception as e:
            print(f"[送信エラー] {e}", flush=True)
            import traceback
            traceback.print_exc()
            reply_message(reply_token, [{"type": "text", "text": "送信中にエラーが発生しました。"}])

    # ---------- 次回準備（クライアント選択後） ----------
    elif action == "prep":
        client_name = params.get("client", "")
        if client_name:
            handle_next_prep(reply_token, client_name)
        else:
            reply_message(reply_token, [{"type": "text", "text": "クライアント名が取得できませんでした。"}])

    # ---------- 体組成記録（クライアント選択後） ----------
    # ---------- 履歴確認 ----------
    elif action == "history_for":
        client_name = params.get("client", "")
        handle_history_view(user_id, reply_token, client_name)

    elif action == "bodycomp_for":
        client_name = params.get("client", "")
        recording_for[user_id] = f"__bodycomp__{client_name}"
        reply_message(reply_token, [{
            "type": "text",
            "text": (
                f"{client_name}さんの体組成を入力してください。\n\n"
                f"例：体重72.5 体脂肪18.5 筋肉量32.0\n"
                f"または：72.5 18.5 32.0\n\n"
                f"体重のみでもOKです。"
            )
        }])

    # ---------- プログラム確認 ----------
    elif action == "program_view":
        client_name = params.get("client", "")
        handle_program_view(reply_token, client_name)

    # ---------- プログラム生成 ----------
    elif action == "program_generate":
        client_name = params.get("client", "")
        handle_program_generate(reply_token, client_name)

    # ---------- スキップ ----------
    elif action == "スキップ":
        reply_message(reply_token, [{"type": "text", "text": "スキップしました。"}])
        sessions.pop(user_id, None)

    # ---------- やり直す ----------
    elif action == "retry":
        sessions.pop(user_id, None)
        reply_message(reply_token, [{"type": "text", "text": "もう一度送ってください。"}])

# ========== 体組成テキスト解析 ==========
def try_parse_body_comp(user_id, reply_token, text):
    """体組成の記録を解析して保存"""
    marker = recording_for.get(user_id, "")
    if not marker.startswith("__bodycomp__"):
        return False

    client_name = marker.replace("__bodycomp__", "")
    recording_for.pop(user_id, None)

    # 数値を抽出
    numbers = re.findall(r'[\d.]+', text)
    weight = numbers[0] if len(numbers) > 0 else ""
    body_fat = numbers[1] if len(numbers) > 1 else ""
    muscle_mass = numbers[2] if len(numbers) > 2 else ""

    if not weight:
        reply_message(reply_token, [{"type": "text", "text": "数値が読み取れませんでした。もう一度入力してください。"}])
        return True

    try:
        gc = get_sheets_client()
        wb = gc.open_by_key(SHEET_ID)

        # 体組成ログシートに記録
        try:
            bc_sheet = wb.worksheet("体組成ログ")
        except gspread.exceptions.WorksheetNotFound:
            bc_sheet = wb.add_worksheet(title="体組成ログ", rows=1000, cols=6)
            bc_sheet.append_row(["日付", "クライアント名", "体重(kg)", "体脂肪率(%)", "筋肉量(kg)", "備考"])

        bc_sheet.append_row([
            datetime.now().strftime("%Y-%m-%d"),
            client_name,
            weight,
            body_fat,
            muscle_mass,
            ""
        ])

        # クライアントマスターの体重も更新
        if weight:
            master_sheet = wb.worksheet("クライアントマスター")
            master_rows = master_sheet.get_all_values()
            target = normalize_name(client_name)
            for i, row in enumerate(master_rows[2:], start=3):
                if normalize_name(row[1] if len(row) > 1 else "") == target:
                    master_sheet.update_cell(i, 6, weight)  # F列 = 体重
                    break

        result_text = f"{client_name}さんの体組成を記録しました。\n\n体重：{weight}kg"
        if body_fat:
            result_text += f"\n体脂肪率：{body_fat}%"
        if muscle_mass:
            result_text += f"\n筋肉量：{muscle_mass}kg"

        reply_message(reply_token, [{"type": "text", "text": result_text}])
    except Exception as e:
        print(f"[体組成記録エラー] {e}", flush=True)
        import traceback
        traceback.print_exc()
        reply_message(reply_token, [{"type": "text", "text": "記録中にエラーが発生しました。"}])

    return True

# ========== プログラム確認 ==========
def handle_program_view(reply_token, client_name):
    try:
        gc = get_sheets_client()
        wb = gc.open_by_key(SHEET_ID)

        try:
            prog_sheet = wb.worksheet("プログラム")
        except gspread.exceptions.WorksheetNotFound:
            reply_message(reply_token, [{
                "type": "text",
                "text": f"{client_name}さんのプログラムはまだありません。\n作成しますか？",
                "quickReply": {"items": [
                    {"type": "action", "action": {"type": "postback", "label": "作成する", "data": f"action=program_generate&client={client_name}"}},
                    {"type": "action", "action": {"type": "postback", "label": "キャンセル", "data": "action=スキップ"}}
                ]}
            }])
            return

        all_rows = prog_sheet.get_all_values()
        target = normalize_name(client_name)
        client_programs = []

        for row in all_rows[1:]:
            name = row[0] if len(row) > 0 else ""
            if normalize_name(name) == target:
                client_programs.append(row)

        if not client_programs:
            reply_message(reply_token, [{
                "type": "text",
                "text": f"{client_name}さんのプログラムはまだありません。\nGPTで作成しますか？",
                "quickReply": {"items": [
                    {"type": "action", "action": {"type": "postback", "label": "作成する", "data": f"action=program_generate&client={client_name}"}},
                    {"type": "action", "action": {"type": "postback", "label": "キャンセル", "data": "action=スキップ"}}
                ]}
            }])
            return

        # プログラム内容を表示
        program_text = f"【{client_name}さんのプログラム】\n\n"
        for row in client_programs:
            day = row[1] if len(row) > 1 else ""
            exercises = row[2] if len(row) > 2 else ""
            notes = row[3] if len(row) > 3 else ""
            program_text += f"■ {day}\n{exercises}\n"
            if notes:
                program_text += f"  備考: {notes}\n"
            program_text += "\n"

        reply_message(reply_token, [{
            "type": "text",
            "text": program_text,
            "quickReply": {"items": [
                {"type": "action", "action": {"type": "postback", "label": "再作成する", "data": f"action=program_generate&client={client_name}"}},
                {"type": "action", "action": {"type": "postback", "label": "クライアントに送信", "data": f"action=program_send&client={client_name}"}}
            ]}
        }])

    except Exception as e:
        print(f"[プログラム確認エラー] {e}", flush=True)
        reply_message(reply_token, [{"type": "text", "text": "データ取得中にエラーが発生しました。"}])

# ========== プログラム自動生成 ==========
def handle_program_generate(reply_token, client_name):
    try:
        # クライアント情報を取得
        info = get_client_info(client_name)
        if not info:
            reply_message(reply_token, [{"type": "text", "text": f"{client_name}さんの情報が見つかりません。"}])
            return

        # 直近セッション記録を取得
        gc = get_sheets_client()
        sheet = gc.open_by_key(SHEET_ID).worksheet("セッションログ")
        all_rows = sheet.get_all_values()
        target = normalize_name(client_name)
        recent_sessions = [r for r in all_rows[1:] if normalize_name(r[2] if len(r) > 2 else "") == target][-5:]

        session_text = ""
        for row in recent_sessions:
            date = row[1] if len(row) > 1 else ""
            menu = row[3] if len(row) > 3 else ""
            session_text += f"{date}: {menu}\n"

        prompt = (
            f"以下のクライアント情報と直近のトレーニング記録に基づいて、"
            f"週3回のトレーニングプログラムを作成してください。\n\n"
            f"【クライアント】{client_name}\n"
            f"目標: {info.get('goal', '未設定')}\n"
            f"注意事項: {info.get('caution', 'なし')}\n"
            f"体重: {info.get('weight', '')}kg / 身長: {info.get('height', '')}cm\n\n"
        )
        if session_text:
            prompt += f"【直近のトレーニング】\n{session_text}\n\n"

        prompt += (
            "以下の形式でJSON出力してください：\n"
            '{"days": [{"day": "Day 1 (部位名)", "exercises": "種目1 3x10\\n種目2 3x12\\n...", "notes": "備考"}]}'
        )

        gpt_res = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "あなたは経験豊富なパーソナルトレーナーです。クライアントに最適なプログラムを作成してください。JSONのみで回答。"},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )

        program_data = json.loads(gpt_res.choices[0].message.content)
        days = program_data.get("days", [])

        # プログラムシートに保存
        wb = gc.open_by_key(SHEET_ID)
        try:
            prog_sheet = wb.worksheet("プログラム")
        except gspread.exceptions.WorksheetNotFound:
            prog_sheet = wb.add_worksheet(title="プログラム", rows=1000, cols=5)
            prog_sheet.append_row(["クライアント名", "Day", "エクササイズ", "備考", "作成日"])

        # 既存のプログラムを削除（同クライアント）
        existing = prog_sheet.get_all_values()
        rows_to_delete = []
        for i, row in enumerate(existing[1:], start=2):
            if normalize_name(row[0] if len(row) > 0 else "") == target:
                rows_to_delete.append(i)

        for row_idx in sorted(rows_to_delete, reverse=True):
            prog_sheet.delete_rows(row_idx)

        # 新しいプログラムを書き込み
        today = datetime.now().strftime("%Y-%m-%d")
        for day in days:
            prog_sheet.append_row([
                client_name,
                day.get("day", ""),
                day.get("exercises", ""),
                day.get("notes", ""),
                today
            ])

        # 結果を表示
        result = f"【{client_name}さんの新プログラム】\n\n"
        for day in days:
            result += f"■ {day.get('day', '')}\n{day.get('exercises', '')}\n"
            if day.get("notes"):
                result += f"  備考: {day['notes']}\n"
            result += "\n"

        reply_message(reply_token, [{
            "type": "text",
            "text": result,
            "quickReply": {"items": [
                {"type": "action", "action": {"type": "postback", "label": "クライアントに送信", "data": f"action=program_send&client={client_name}"}},
                {"type": "action", "action": {"type": "postback", "label": "OK", "data": "action=スキップ"}}
            ]}
        }])

    except Exception as e:
        print(f"[プログラム生成エラー] {e}", flush=True)
        import traceback
        traceback.print_exc()
        reply_message(reply_token, [{"type": "text", "text": "プログラム生成中にエラーが発生しました。"}])

# ========== Google Sheets書き込み ==========
def write_to_sheets(session):
    gc = get_sheets_client()
    workbook = gc.open_by_key(SHEET_ID)
    sheet = workbook.worksheet("セッションログ")
    all_rows = sheet.get_all_values()
    no = len(all_rows) - 1
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    client_name = session.get("clientName", "")
    exercises = session.get("exercises", [])
    exercises_json = json.dumps(exercises, ensure_ascii=False) if exercises else ""

    sheet.append_row([
        now,
        no,
        client_name,
        session.get("menu", ""),
        session.get("memo", ""),
        exercises_json,
        "未送信"
    ])

    # クライアント別の種目別ログシートに書き込み
    if exercises and client_name:
        sheet_name = f"種目_{client_name}"
        try:
            ex_sheet = workbook.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            ex_sheet = workbook.add_worksheet(title=sheet_name, rows=1000, cols=7)
            ex_sheet.append_row(["日時", "種目名", "重量", "セット", "レップ", "備考", "セッションNo"])

        ex_rows = []
        for ex in exercises:
            ex_rows.append([
                now,
                ex.get("name", ""),
                str(ex.get("weight", "")) if ex.get("weight") else "",
                str(ex.get("sets", "")) if ex.get("sets") else "",
                str(ex.get("reps", "")) if ex.get("reps") else "",
                ex.get("note", ""),
                no
            ])
        if ex_rows:
            ex_sheet.append_rows(ex_rows)

# ========== 名前で最新の未送信レコードを送信済みに更新 ==========
def update_send_status_by_name(client_name):
    gc = get_sheets_client()
    sheet = gc.open_by_key(SHEET_ID).worksheet("セッションログ")
    all_rows = sheet.get_all_values()

    for i in range(len(all_rows) - 1, 0, -1):
        row = all_rows[i]
        name = row[2] if len(row) > 2 else ""
        status = row[7] if len(row) > 7 else ""
        if name == client_name and status == "未送信":
            sheet.update_cell(i + 1, 8, "送信済み")
            break

# ========== テキスト処理（体組成対応追加） ==========
# handle_text を上書き：体組成入力待ちの場合はそちらを優先
_original_handle_text = handle_text

def handle_text(user_id, reply_token, text):
    # 体組成入力待ちの場合
    marker = recording_for.get(user_id, "")
    if marker.startswith("__bodycomp__"):
        try_parse_body_comp(user_id, reply_token, text)
        return
    _original_handle_text(user_id, reply_token, text)

# ========== 起動 ==========
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

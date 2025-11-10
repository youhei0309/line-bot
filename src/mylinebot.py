"""
Line Bot
"""

import os

from linebot import (
    LineBotApi, WebhookHandler
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, ImageMessage
)

# PythonからAWSを操作できるライブラリ
import boto3

# Lambdaの環境変数からLINEのチャネルシークレットとアクセストークンを取得
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
client = boto3.client('rekognition')

# AWS Lambda が呼び出す関数
# API Gateway → Lambda 関数 に渡される全ての情報（ヘッダー・ボディなど）は event に格納される
def lambda_handler(event, context):
    # ヘッダー情報を取得（LINEの署名検証に使う）
    headers = event["headers"]
    # ボディ（＝ユーザーからのメッセージ等のイベント本体）を取得
    body = event["body"]
    # LINEから送られてくる署名を取得
    signature = headers['x-line-signature']
    # 条件に合うイベントを探して、対応する関数を実行する
    handler.handle(body, signature)
    # API Gateway に成功レスポンスを返す（HTTP 200 OK)
    return {"statusCode": 200, "body": "OK"}

# オウム返し処理
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    """ TextMessage handler """
    input_text = event.message.text

    # 返信する関数(LineBotApiライブラリ)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=input_text))

# 画像解析(Rekognitionサービス)処理
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    # ユーザーから送られてきた画像を一時ファイルとして保存
    message_content = line_bot_api.get_message_content(event.message.id)
    # Lambdaローカルストレージ上ではtmpの配下にしか書き込みができない
    file_path = "/tmp/sent-image.jpg"
    # 画像データをバイナリで書き込み
    with open(file_path,'wb') as fd:
        for chunk in message_content.iter_content():
            fd.write(chunk)

    # 画像のバイナリデータを読み取る
    with open(file_path,'rb') as fd:
        send_image_binary = fd.read()
        # 顔写真解析処理(detect_faces関数)
        face_response = client.detect_faces(Image={"Bytes":send_image_binary},Attributes=["ALL"])
        # 有名人解析処理(recognize_celebrities関数)
        celeb_response = client.recognize_celebrities(Image={"Bytes":send_image_binary})
        # 文字画像解析処理(detect_text関数)
        text_response = client.detect_text(Image={"Bytes":send_image_binary})

    message_text = get_Image_message(face_response, celeb_response, text_response)

    # 返答を送信する
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=message_text)
    )

    # 一時保存した画像を削除する
    os.remove(file_path)

# 画像解析結果メッセージ作成関数
def get_Image_message(face_response, celeb_response, text_response):
    # face_response から "FaceDetails" というキーを取り出す
    face_details = face_response.get("FaceDetails", [])

    # 顔写真結果データが取得できている場合(顔写真解析優先)
    if face_details:
        # 年齢範囲情報の取得
        age_range = face_details[0].get("AgeRange", {})
        age_text = f"{age_range.get('Low','?')}-{age_range.get('High','?')}歳"

        # 性別情報の取得
        gender_info = face_details[0].get("Gender", {})
        gender_value = gender_info.get('Value','不明')
        # 日本語に変換
        if gender_value == "Male":
            gender_text_value = "男性"
        elif gender_value == "Female":
            gender_text_value = "女性"
        else:
            gender_text_value = "不明"
        gender_text = f"{gender_text_value} ({int(gender_info.get('Confidence',0))}%)"

        # 感情の取得
        emotions = face_details[0].get("Emotions", [])
        if not emotions:
            emotion_text = "感情が検出できませんでした。"
        else:
            # 一番確信度の高い感情を取得
            top_emotion = max(emotions, key=lambda e: e['Confidence'])
            # 一番確信度の高い感情の 種類（Type）だけを取り出す
            emotion_type = top_emotion['Type']
            # 感情ごとの返信メッセージ
            messages = {
                "HAPPY": "楽しそうですね！いい気分が伝わってきます。",
                "SAD": "何か悲しいことがありましたか？大丈夫ですか？",
                "ANGRY": "怒っているみたいですね。リラックスしましょう。",
                "SURPRISED": "驚いた顔ですね！何かいいことがありましたか？",
                "CALM": "落ち着いた感じがいいですね。",
                "CONFUSED": "少し混乱しているみたいですね。",
                # 他の感情も必要に応じて追加
            }
            # messages から emotion_type に対応するメッセージを取得して返す
            # messagesにない感情タイプの場合、デフォルトメッセージ "感情は〇〇のようですね。" を返す
            emotion_text = messages.get(emotion_type, f"{emotion_type}のようですね。")

        # 有名人情報の取得
        celebrities = celeb_response.get("CelebrityFaces", [])

        # 1件以上の有名人情報が格納されている場合
        if celebrities:
            # それぞれの有名人の名前と一致率の一覧を取得
            celeb_info = [(celeb.get("Name","不明"), celeb.get("MatchConfidence", 0)) for celeb in celebrities]
            # 最も一致率が高い有名人を取得
            top_celeb = max(celeb_info, key=lambda x: x[1])
            # 2つの変数に展開（アンパック）する 　(例):top_celeb = ("Tom Cruise", 87.3)
            celeb_name, celeb_conf = top_celeb
            # メッセージ作成
            celeb_text = f"{celeb_name} ({celeb_conf:.1f}%)"

        else:
            celeb_text = "有名人は検出できませんでした。"

        # 顔写解析結果メッセージを返す
        return f"・推定年齢: {age_text}\n・性別: {gender_text}\n・感情：{emotion_text}\n・最も似ている有名人: {celeb_text}"
        
    # 顔写真結果データが取得できていない場合(文字画像解析を実行)
    else:
        # text_response から "TextDetections" というキーを取り出す
        detected_texts = text_response.get("TextDetections", [])
        # 画像中の単一行テキストだけを抽出して文字列のリストへ格納
        # 「LINE（単一行のテキスト）」 のものだけを対象とする
        texts = [t['DetectedText'] for t in detected_texts if t['Type'] == 'LINE']
        # 単一行のテキストを結合して表示
        if texts:
            return "\n".join(texts)
        else:
            return "顔も文字も検出できませんでした。"
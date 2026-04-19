"""
BNF式 通知システム v6.4.1 本番運用版（S&P500フィルター追加）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【v6.4 → v6.4.1 の変更】
  ★ S&P500 前日-3% 停止条件を追加 ★
  ★ 米国発ショック（コロナ等）への備え強化 ★

【機能】
  毎朝8:30に自動スキャン
  通常時: BNFシグナル配信
  暴落時: エントリー禁止アラート

【暴落判定（v6.4.1）】
  1. VIX > 45
  2. 日経平均1日変動 < -5%
  3. 日経25日MA乖離 < -15%
  4. S&P500 前日 < -3% ← ★v6.4.1追加

【バックテスト実績】
  10年: 勝率64.2% / PF2.98 / リターン+207,889% / DD73%
  15年: 勝率59.0% / PF2.36 / リターン+7,399,489% / DD73%

【Gmail設定（★要編集★）】
  1. https://myaccount.google.com/apppasswords でアプリパスワード取得
  2. 下記のGMAIL_CONFIGを編集
  3. python bnf_notify.py --test で動作確認

【実行方法】
  python bnf_notify.py --test     # テスト送信
  python bnf_notify.py             # 今すぐ1回スキャン
  python bnf_notify.py --watch     # 毎朝8:30自動（常時稼働）
"""

import os, sys, smtplib, ssl, datetime, warnings
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate

def check_libs():
    missing = []
    for lib in ["yfinance", "pandas", "schedule"]:
        try: __import__(lib)
        except ImportError: missing.append(lib)
    if missing:
        print(f"pip install {' '.join(missing)}")
        sys.exit(1)

check_libs()
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import schedule
import time

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📧 Gmail設定（環境変数経由。GitHub Secretsから読み込み）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GMAIL_CONFIG = {
    "from_email":   os.environ.get("GMAIL_FROM", ""),
    "app_password": os.environ.get("GMAIL_APP_PASSWORD", ""),
    "to_email":     os.environ.get("GMAIL_TO", ""),
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 監視銘柄（v6.4と完全に同じ・277銘柄）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JAPAN_STOCKS = {
    # 銀行
    "8306.T":("三菱UFJフィナンシャルG","銀行",13),
    "8316.T":("三井住友フィナンシャルG","銀行",13),
    "8411.T":("みずほフィナンシャルG","銀行",13),
    "8309.T":("三井住友トラスト","銀行",13),
    "8308.T":("りそなHD","銀行",13),
    "8354.T":("ふくおかFG","銀行",15),
    "8331.T":("千葉銀行","銀行",15),
    "8377.T":("ほくほくFG","銀行",15),
    "7186.T":("コンコルディアFG","銀行",15),
    "8388.T":("阿波銀行","銀行",15),
    "8418.T":("山口フィナンシャルG","銀行",15),
    "8386.T":("百十四銀行","銀行",15),
    "8385.T":("伊予銀行","銀行",15),
    "8334.T":("群馬銀行","銀行",15),
    "8253.T":("クレディセゾン","銀行",16),
    "8591.T":("オリックス","銀行",15),
    "8473.T":("SBIホールディングス","銀行",17),
    "8425.T":("みずほリース","銀行",16),
    "7164.T":("全国保証","銀行",14),
    "8572.T":("アコム","銀行",15),
    "8570.T":("イオンフィナンシャル","銀行",15),
    "8566.T":("リコーリース","銀行",14),
    "8424.T":("芙蓉総合リース","銀行",14),
    "8584.T":("ジャックス","銀行",15),
    "8341.T":("七十七銀行","銀行",15),
    "8336.T":("武蔵野銀行","銀行",15),
    # 保険
    "8766.T":("東京海上HD","保険",15),
    "8750.T":("第一生命HD","保険",15),
    "8725.T":("MS&ADインシュアランス","保険",15),
    "8630.T":("SOMPOホールディングス","保険",15),
    "8795.T":("T&D HD","保険",15),
    # 証券
    "8601.T":("大和証券G本社","証券",14),
    "8604.T":("野村HD","証券",14),
    "8697.T":("日本取引所グループ","証券",14),
    "8698.T":("マネックスG","証券",18),
    "8628.T":("松井証券","証券",16),
    # 商社
    "8058.T":("三菱商事","商社",13),
    "8001.T":("伊藤忠商事","商社",13),
    "8002.T":("丸紅","商社",13),
    "8031.T":("三井物産","商社",13),
    "8053.T":("住友商事","商社",13),
    "8015.T":("豊田通商","商社",13),
    "2768.T":("双日","商社",14),
    "8130.T":("サンゲツ","商社",14),
    "8052.T":("椿本興業","商社",14),
    "8074.T":("ユアサ商事","商社",14),
    "8078.T":("阪和興業","商社",14),
    "8097.T":("三愛オブリ","商社",14),
    "9830.T":("トラスコ中山","商社",14),
    # 自動車
    "7203.T":("トヨタ自動車","自動車",14),
    "7267.T":("ホンダ","自動車",14),
    "7201.T":("日産自動車","自動車",16),
    "7269.T":("スズキ","自動車",14),
    "7270.T":("SUBARU","自動車",14),
    "6902.T":("デンソー","自動車",14),
    "7211.T":("三菱自動車","自動車",18),
    "7205.T":("日野自動車","自動車",16),
    "7261.T":("マツダ","自動車",16),
    "7272.T":("ヤマハ発動機","自動車",14),
    "5108.T":("ブリヂストン","自動車",13),
    "5101.T":("横浜ゴム","自動車",14),
    "5110.T":("住友ゴム工業","自動車",14),
    "7276.T":("小糸製作所","自動車",14),
    "7282.T":("豊田合成","自動車",14),
    "7259.T":("アイシン","自動車",14),
    "6201.T":("豊田自動織機","自動車",14),
    "7240.T":("NOK","自動車",14),
    "7296.T":("エフ・シー・シー","自動車",14),
    "7250.T":("太平洋工業","自動車",14),
    "3116.T":("トヨタ紡織","自動車",14),
    "3105.T":("日清紡HD","自動車",14),
    "5105.T":("TOYO TIRE","自動車",15),
    # 半導体
    "8035.T":("東京エレクトロン","半導体",20),
    "6857.T":("アドバンテスト","半導体",20),
    "6920.T":("レーザーテック","半導体",23),
    "4063.T":("信越化学工業","半導体",20),
    "6981.T":("村田製作所","半導体",20),
    "6762.T":("TDK","半導体",20),
    "6770.T":("アルプスアルパイン","半導体",20),
    "6723.T":("ルネサスエレクトロニクス","半導体",20),
    "3436.T":("SUMCO","半導体",22),
    "6146.T":("ディスコ","半導体",22),
    "6963.T":("ローム","半導体",20),
    "7735.T":("スクリーンHD","半導体",22),
    "6645.T":("オムロン","半導体",20),
    "6674.T":("GSユアサ","半導体",20),
    "6728.T":("アルバック","半導体",20),
    "6951.T":("日本電子","半導体",20),
    "6965.T":("浜松ホトニクス","半導体",20),
    # IT（v6.3で引き上げ）
    "6702.T":("富士通","IT",20),
    "6701.T":("NEC","IT",20),
    "9984.T":("ソフトバンクG","IT",22),
    "4689.T":("LINEヤフー","IT",22),
    "4307.T":("野村総合研究所","IT",20),
    "4704.T":("トレンドマイクロ","IT",20),
    "4755.T":("楽天グループ","IT",22),
    "3659.T":("ネクソン","IT",22),
    "9766.T":("コナミG","IT",22),
    "2413.T":("エムスリー","IT",22),
    "4751.T":("サイバーエージェント","IT",22),
    "6098.T":("リクルートHD","IT",20),
    "2127.T":("日本M&AセンターHD","IT",22),
    "3697.T":("SHIFT","IT",24),
    "2432.T":("DeNA","IT",22),
    "3769.T":("GMOペイメントGW","IT",22),
    "3923.T":("ラクス","IT",22),
    # 電機
    "6501.T":("日立製作所","電機",16),
    "6758.T":("ソニーグループ","電機",18),
    "6752.T":("パナソニックHD","電機",16),
    "6503.T":("三菱電機","電機",14),
    "6506.T":("安川電機","電機",18),
    "6841.T":("横河電機","電機",16),
    "6367.T":("ダイキン工業","電機",14),
    "6753.T":("シャープ","電機",18),
    "6504.T":("富士電機","電機",14),
    "6592.T":("マブチモーター","電機",16),
    "6806.T":("ヒロセ電機","電機",16),
    # 精密
    "6594.T":("ニデック","精密",20),
    "6861.T":("キーエンス","精密",20),
    "7751.T":("キヤノン","精密",16),
    "7741.T":("HOYA","精密",18),
    "6971.T":("京セラ","精密",16),
    "7733.T":("オリンパス","精密",18),
    "4901.T":("富士フイルムHD","精密",16),
    "6856.T":("堀場製作所","精密",18),
    "6869.T":("シスメックス","精密",18),
    "7762.T":("シチズン時計","精密",16),
    "6724.T":("セイコーエプソン","精密",16),
    "7832.T":("バンダイナムコHD","精密",18),
    "6954.T":("ファナック","精密",20),
    "6952.T":("カシオ計算機","精密",18),
    # 鉄鋼
    "5401.T":("日本製鉄","鉄鋼",17),
    "5411.T":("JFEホールディングス","鉄鋼",17),
    "5713.T":("住友金属鉱山","鉄鋼",17),
    "5714.T":("DOWAホールディングス","鉄鋼",17),
    "5706.T":("三井金属鉱業","鉄鋼",17),
    "5802.T":("住友電気工業","鉄鋼",15),
    "5803.T":("フジクラ","鉄鋼",15),
    "5703.T":("日本軽金属HD","鉄鋼",15),
    "5901.T":("東洋製罐G","鉄鋼",14),
    "5711.T":("三菱マテリアル","鉄鋼",16),
    # 化学
    "4188.T":("三菱ケミカルG","化学",17),
    "4183.T":("三井化学","化学",17),
    "3402.T":("東レ","化学",17),
    "4005.T":("住友化学","化学",15),
    "3407.T":("旭化成","化学",15),
    "4004.T":("レゾナック","化学",17),
    "4021.T":("日産化学","化学",15),
    "4061.T":("デンカ","化学",15),
    "4091.T":("日本酸素HD","化学",14),
    "4118.T":("カネカ","化学",15),
    "4202.T":("ダイセル","化学",15),
    "4204.T":("積水化学工業","化学",15),
    "4208.T":("UBE","化学",15),
    "4631.T":("DIC","化学",15),
    "4911.T":("資生堂","化学",15),
    "3405.T":("クラレ","化学",15),
    "4452.T":("花王","化学",12),
    "4042.T":("東ソー","化学",15),
    # エネルギー
    "5020.T":("ENEOSホールディングス","エネルギー",17),
    "5019.T":("出光興産","エネルギー",17),
    "1605.T":("INPEX","エネルギー",19),
    "9501.T":("東京電力HD","エネルギー",19),
    "9502.T":("中部電力","エネルギー",16),
    "9503.T":("関西電力","エネルギー",16),
    "9504.T":("中国電力","エネルギー",16),
    "9531.T":("東京ガス","エネルギー",16),
    "9532.T":("大阪ガス","エネルギー",16),
    "9533.T":("東邦ガス","エネルギー",16),
    # 海運
    "9101.T":("日本郵船","海運",20),
    "9104.T":("商船三井","海運",20),
    "9107.T":("川崎汽船","海運",20),
    # 陸運
    "9020.T":("東日本旅客鉄道","陸運",16),
    "9021.T":("西日本旅客鉄道","陸運",16),
    "9022.T":("東海旅客鉄道","陸運",16),
    "9142.T":("九州旅客鉄道","陸運",16),
    "9005.T":("東急","陸運",16),
    "9007.T":("小田急電鉄","陸運",16),
    "9008.T":("京王電鉄","陸運",16),
    "9009.T":("京成電鉄","陸運",16),
    "9001.T":("東武鉄道","陸運",16),
    "9006.T":("京浜急行電鉄","陸運",16),
    "9044.T":("南海電気鉄道","陸運",16),
    "9045.T":("京阪HD","陸運",16),
    "9048.T":("名古屋鉄道","陸運",16),
    "9064.T":("ヤマトHD","陸運",16),
    "9147.T":("NIPPON EXPRESS HD","陸運",16),
    # 空運
    "9202.T":("ANAホールディングス","空運",16),
    "9201.T":("日本航空","空運",16),
    # 不動産
    "8801.T":("三井不動産","不動産",16),
    "8802.T":("三菱地所","不動産",16),
    "8804.T":("東京建物","不動産",16),
    "8830.T":("住友不動産","不動産",16),
    "3003.T":("ヒューリック","不動産",16),
    "3289.T":("東急不動産HD","不動産",16),
    "3231.T":("野村不動産HD","不動産",16),
    "1925.T":("大和ハウス工業","不動産",16),
    "1928.T":("積水ハウス","不動産",16),
    "3288.T":("オープンハウス","不動産",17),
    "3291.T":("飯田グループHD","不動産",16),
    # 建設
    "1801.T":("大成建設","建設",17),
    "1803.T":("清水建設","建設",17),
    "1802.T":("大林組","建設",17),
    "1812.T":("鹿島建設","建設",17),
    "1963.T":("日揮HD","建設",19),
    "1942.T":("関電工","建設",16),
    "1944.T":("きんでん","建設",16),
    "1720.T":("東急建設","建設",17),
    "1721.T":("コムシスHD","建設",16),
    "1719.T":("安藤・間","建設",17),
    "1820.T":("西松建設","建設",17),
    "1878.T":("大東建託","建設",16),
    "1893.T":("五洋建設","建設",17),
    "1762.T":("高松コンスト","建設",17),
    "1860.T":("戸田建設","建設",17),
    "1861.T":("熊谷組","建設",17),
    "1949.T":("住友電設","建設",16),
    "1950.T":("日本電設工業","建設",16),
    "1951.T":("エクシオG","建設",16),
    "1959.T":("九電工","建設",16),
    # 機械
    "6301.T":("コマツ","機械",15),
    "6302.T":("住友重機械工業","機械",15),
    "6305.T":("日立建機","機械",16),
    "6326.T":("クボタ","機械",15),
    "7013.T":("IHI","機械",16),
    "7011.T":("三菱重工業","機械",15),
    "6361.T":("荏原製作所","機械",15),
    "6370.T":("栗田工業","機械",15),
    "6383.T":("ダイフク","機械",16),
    "7003.T":("三井E&S","機械",16),
    "6103.T":("オークマ","機械",16),
    "6113.T":("アマダ","機械",15),
    "6141.T":("DMG森精機","機械",16),
    "6273.T":("SMC","機械",16),
    "6366.T":("千代田化工建設","機械",16),
    "6268.T":("ナブテスコ","機械",15),
    "7012.T":("川崎重工業","機械",16),
    "6471.T":("日本精工","機械",15),
    "6472.T":("NTN","機械",15),
    "6473.T":("ジェイテクト","機械",15),
    # ゲーム
    "9684.T":("スクウェア・エニックスHD","ゲーム",18),
    "9697.T":("カプコン","ゲーム",16),
    "7974.T":("任天堂","ゲーム",16),
    "6460.T":("セガサミーHD","ゲーム",18),
    "4680.T":("ラウンドワン","ゲーム",18),
    # 食品
    "2802.T":("味の素","食品",13),
    "2914.T":("JT","食品",13),
    "2267.T":("ヤクルト本社","食品",13),
    "2502.T":("アサヒグループHD","食品",13),
    "2503.T":("キリンHD","食品",13),
    "2269.T":("明治HD","食品",13),
    "2282.T":("日本ハム","食品",13),
    "2002.T":("日清製粉G本社","食品",13),
    "2801.T":("キッコーマン","食品",13),
    "2810.T":("ハウス食品G本社","食品",13),
    "2871.T":("ニチレイ","食品",13),
    "2897.T":("日清食品HD","食品",13),
    "2593.T":("伊藤園","食品",13),
    "2206.T":("江崎グリコ","食品",13),
    "2270.T":("雪印メグミルク","食品",13),
    "2531.T":("宝HD","食品",13),
    "2579.T":("コカ・コーラBJH","食品",13),
    "2001.T":("ニップン","食品",13),
    "2875.T":("東洋水産","食品",13),
    "2281.T":("プリマハム","食品",13),
    "2809.T":("キユーピー","食品",13),
    "2811.T":("カゴメ","食品",13),
    # サービス
    "9602.T":("東宝","サービス",16),
    "9401.T":("TBSホールディングス","サービス",15),
    "9404.T":("日本テレビHD","サービス",15),
    "9413.T":("テレビ東京HD","サービス",15),
    "4324.T":("電通グループ","サービス",16),
    "9735.T":("セコム","サービス",15),
    "2175.T":("エス・エム・エス","サービス",18),
    "9301.T":("三菱倉庫","サービス",15),
    "9302.T":("三井倉庫HD","サービス",15),
    "9303.T":("住友倉庫","サービス",15),
    "4816.T":("東映アニメーション","サービス",18),
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 運用設定（★自分の資金に合わせて編集★）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TRADING_CONFIG = {
    "total_capital": 1_000_000,  # 総運用資金（100万円）
    "investment_rate": 0.30,      # 1銘柄あたり投入率（30%）
    "stop_loss_pct": -5.0,        # 損切りライン
    "max_hold_days": 14,          # 最大保有日数
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 暴落判定（v6.4.1 = v6.4 + S&P500フィルター）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def check_crash():
    """今日が暴落日かチェック"""
    print("  🔍 暴落判定指標を取得中...")
    crash_reasons = []
    details = {}

    # 1. VIX > 45（歴史的パニック）
    try:
        vix_df = yf.download("^VIX", period="1mo", interval="1d",
                              progress=False, auto_adjust=True)
        if not vix_df.empty:
            vix = float(vix_df["Close"].iloc[-1])
            details["VIX"] = f"{vix:.1f}"
            if vix > 45:
                crash_reasons.append(f"VIX={vix:.0f} (歴史的パニック)")
    except: pass

    # 2・3. 日経平均（-5%急落 / 25日MA乖離-15%）
    try:
        nk_df = yf.download("^N225", period="3mo", interval="1d",
                             progress=False, auto_adjust=True)
        if not nk_df.empty:
            close = nk_df["Close"].squeeze()
            nk_now = float(close.iloc[-1])
            details["日経平均"] = f"{nk_now:,.0f}円"

            if len(close) >= 2:
                chg = (nk_now - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
                details["前日比"] = f"{chg:+.2f}%"
                if chg < -5:
                    crash_reasons.append(f"日経{chg:.1f}% (急落)")

            if len(close) >= 25:
                ma25 = float(close.tail(25).mean())
                dev = (nk_now - ma25) / ma25 * 100
                details["25日MA乖離"] = f"{dev:+.1f}%"
                if dev < -15:
                    crash_reasons.append(f"MA乖離{dev:.1f}% (深い調整)")
    except: pass

    # 4. ★v6.4.1 追加: S&P500 前日 -3%以下（米国発ショック）
    try:
        sp_df = yf.download("^GSPC", period="1mo", interval="1d",
                             progress=False, auto_adjust=True)
        if not sp_df.empty:
            sp_close = sp_df["Close"].squeeze()
            if len(sp_close) >= 2:
                sp_now = float(sp_close.iloc[-1])
                sp_prev = float(sp_close.iloc[-2])
                sp_chg = (sp_now - sp_prev) / sp_prev * 100
                details["S&P500前日比"] = f"{sp_chg:+.2f}%"
                if sp_chg < -3:
                    crash_reasons.append(f"S&P500{sp_chg:.1f}% (米国発ショック)")
    except: pass

    is_crash = len(crash_reasons) > 0
    return is_crash, crash_reasons, details

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# シグナルスキャン（v6.4ロジック）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def scan_signals():
    """BNFシグナルを277銘柄からスキャン"""
    signals = []
    print(f"  🔍 {len(JAPAN_STOCKS)}銘柄をスキャン中（5〜10分かかります）...")

    count = 0
    for ticker, (name, sector, threshold) in JAPAN_STOCKS.items():
        count += 1
        if count % 50 == 0:
            print(f"    進行: {count}/{len(JAPAN_STOCKS)}銘柄")
        try:
            df = yf.download(ticker, period="3mo", interval="1d",
                             progress=False, auto_adjust=True)
            if df.empty or len(df) < 30: continue
            close = df["Close"].squeeze()
            volume = df["Volume"].squeeze()
            ma25 = close.rolling(25).mean()
            std25 = close.rolling(25).std()
            bb2 = ma25 - 2*std25
            vol_ma20 = volume.rolling(20).mean()

            price = float(close.iloc[-1])
            ma = float(ma25.iloc[-1])
            bb2v = float(bb2.iloc[-1])
            vol = float(volume.iloc[-1])
            vola = float(vol_ma20.iloc[-1])
            vol_pct = vol/vola*100 if vola > 0 else 100

            dev = (price - ma) / ma * 100
            if dev >= 0: continue
            if abs(dev) < threshold: continue

            c1 = abs(dev) >= threshold
            c2 = vol_pct >= 110
            c3 = price <= bb2v
            score = sum([c1, c2, c3])
            if score < 2: continue

            # 30万円で買える株数を計算
            invest_amount = TRADING_CONFIG["total_capital"] * TRADING_CONFIG["investment_rate"]
            shares = int(invest_amount / price / 100) * 100  # 100株単位
            actual_cost = shares * price

            signals.append({
                "code": ticker.replace(".T",""),
                "name": name,
                "sector": sector,
                "price": price,
                "deviation": round(dev, 1),
                "threshold": threshold,
                "vol_pct": round(vol_pct),
                "score": score,
                "c1": c1, "c2": c2, "c3": c3,
                "sl": round(price * (1 + TRADING_CONFIG["stop_loss_pct"]/100)),
                "target": round(ma),
                "profit": round((ma-price)/price*100, 1),
                "shares": shares,
                "cost": round(actual_cost),
            })
        except: pass

    signals.sort(key=lambda x: (-x["score"], x["deviation"]))
    return signals[:10]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メール作成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def build_email_html(is_crash, crash_reasons, details, signals):
    now = datetime.datetime.now()
    date_str = now.strftime("%Y年%m月%d日（%a）")

    if is_crash:
        status_color = "#FF3355"
        status_label = "🚨 暴落警報"
        status_msg = "本日はエントリー禁止"
    else:
        status_color = "#00FF88"
        status_label = "🟢 通常運用"
        status_msg = "本日はエントリー可能"

    details_html = "".join(
        f'<tr><td style="padding:5px 10px;color:#888">{k}</td>'
        f'<td style="padding:5px 10px;text-align:right;color:#fff;font-family:monospace">{v}</td></tr>'
        for k, v in details.items()
    )

    if is_crash:
        reasons_html = "<br>".join(f"• {r}" for r in crash_reasons)
        main_html = f'''
        <div style="background:#3d1b1b;border:2px solid #FF3355;border-radius:8px;padding:24px;text-align:center;">
          <div style="font-size:48px;margin-bottom:12px;">🚨</div>
          <div style="color:#FF3355;font-size:20px;font-weight:bold;margin-bottom:12px;">本日は暴落相場</div>
          <div style="color:#ccc;font-size:13px;line-height:1.8;margin-bottom:16px;">
            <b>検出された暴落条件:</b><br>
            {reasons_html}
          </div>
          <div style="background:rgba(0,0,0,0.3);padding:14px;border-radius:6px;color:#ccc;font-size:12px;line-height:1.7;">
            📌 <b>推奨アクション</b><br>
            ・エントリー完全停止<br>
            ・現金維持で次のチャンスを待機<br>
            ・既存ポジションは損切りライン厳守
          </div>
          <div style="margin-top:16px;font-style:italic;font-size:12px;color:#888;">
            「下げ相場ではコツコツ負けてドカンと勝つ」— BNF
          </div>
        </div>
        '''
    elif not signals:
        main_html = f'''
        <div style="background:#1a1f2e;border:1px solid #2a3040;border-radius:8px;padding:24px;text-align:center;color:#888;">
          <div style="font-size:36px;margin-bottom:10px;opacity:0.5;">📊</div>
          <div style="font-size:14px;line-height:1.7;">
            本日は該当するシグナルがありません<br>
            相場を落ち着いて見守りましょう
          </div>
          <div style="margin-top:16px;font-style:italic;font-size:11px;">
            「待てる人が最終的に勝つ」— BNF
          </div>
        </div>
        '''
    else:
        signals_html = ""
        for s in signals:
            star_color = "#00FF88" if s["score"] == 3 else "#FFB800"
            dots = "".join(
                f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
                f'background:{"#00FF88" if c else "#333"};margin:0 2px;"></span>'
                for c in [s["c1"], s["c2"], s["c3"]]
            )
            signals_html += f'''
            <div style="background:#1a1f2e;border-left:3px solid {star_color};border-radius:8px;padding:14px;margin-bottom:10px;">
              <table width="100%" style="border-collapse:collapse;">
                <tr>
                  <td>
                    <div style="color:#888;font-size:11px;font-family:monospace;">{s["code"]}</div>
                    <div style="color:#fff;font-size:15px;font-weight:bold;margin:2px 0;">{s["name"]}</div>
                    <span style="color:#888;font-size:10px;border:1px solid #333;padding:2px 6px;border-radius:3px;">{s["sector"]}</span>
                  </td>
                  <td style="text-align:right;">
                    <div>{dots}</div>
                    <div style="color:#666;font-size:10px;margin-top:3px;">{s["score"]}/3点</div>
                  </td>
                </tr>
              </table>
              <table width="100%" style="margin-top:10px;border-collapse:collapse;">
                <tr>
                  <td style="background:rgba(0,0,0,0.3);padding:6px;text-align:center;border-radius:4px;">
                    <div style="color:#666;font-size:9px;">現在値</div>
                    <div style="color:#00D4FF;font-size:13px;font-weight:bold;font-family:monospace;">¥{s["price"]:,.0f}</div>
                  </td>
                  <td style="padding:0 4px;"></td>
                  <td style="background:rgba(0,0,0,0.3);padding:6px;text-align:center;border-radius:4px;">
                    <div style="color:#666;font-size:9px;">乖離率</div>
                    <div style="color:#00FF88;font-size:13px;font-weight:bold;font-family:monospace;">{s["deviation"]}%</div>
                  </td>
                  <td style="padding:0 4px;"></td>
                  <td style="background:rgba(0,0,0,0.3);padding:6px;text-align:center;border-radius:4px;">
                    <div style="color:#666;font-size:9px;">出来高</div>
                    <div style="color:#FFB800;font-size:13px;font-weight:bold;font-family:monospace;">+{s["vol_pct"]}%</div>
                  </td>
                </tr>
              </table>
              <div style="background:rgba(0,212,255,0.1);padding:10px;margin-top:8px;border-radius:4px;">
                <div style="color:#888;font-size:10px;margin-bottom:4px;">💰 30万円での購入プラン</div>
                <div style="color:#00D4FF;font-size:13px;font-weight:bold;font-family:monospace;">
                  {s["shares"]}株 × ¥{s["price"]:,.0f} = ¥{s["cost"]:,}
                </div>
              </div>
              <table width="100%" style="margin-top:8px;border-collapse:collapse;">
                <tr>
                  <td style="background:rgba(255,51,85,0.1);padding:6px 10px;border-radius:4px;">
                    <span style="color:#888;font-size:10px;">🔴 損切(-5%)</span>
                    <span style="color:#FF3355;font-size:12px;font-weight:bold;float:right;font-family:monospace;">¥{s["sl"]:,}</span>
                  </td>
                  <td style="padding:0 4px;"></td>
                  <td style="background:rgba(0,255,136,0.1);padding:6px 10px;border-radius:4px;">
                    <span style="color:#888;font-size:10px;">🎯 利確目標</span>
                    <span style="color:#00FF88;font-size:12px;font-weight:bold;float:right;font-family:monospace;">¥{s["target"]:,}</span>
                  </td>
                </tr>
              </table>
            </div>
            '''
        main_html = signals_html

    html = f'''<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0A0E1A;font-family:'Hiragino Sans',sans-serif;color:#E2EBF6;">
<div style="max-width:600px;margin:0 auto;padding:20px;">

<div style="background:#0D1422;border-bottom:1px solid #1F2D45;padding:16px;border-radius:8px 8px 0 0;">
  <table width="100%">
    <tr>
      <td>
        <span style="background:#00FF88;color:#000;font-family:monospace;font-size:11px;font-weight:bold;padding:4px 10px;letter-spacing:2px;border-radius:3px;">BNF v6.4.1</span>
        <span style="color:#888;font-size:12px;margin-left:10px;">277銘柄・セクター最適化版</span>
      </td>
      <td style="text-align:right;color:#888;font-size:11px;font-family:monospace;">{date_str}</td>
    </tr>
  </table>
</div>

<div style="background:#111827;padding:20px;border:1px solid #1F2D45;">
  <div style="color:#666;font-size:10px;text-transform:uppercase;letter-spacing:2px;margin-bottom:8px;">MARKET STATUS</div>
  <div style="font-size:22px;font-weight:bold;color:{status_color};margin-bottom:4px;">{status_label}</div>
  <div style="color:#ccc;font-size:13px;margin-bottom:12px;">{status_msg}</div>
  <table width="100%" style="border-collapse:collapse;font-size:11px;">
    {details_html}
  </table>
</div>

<div style="background:#111827;padding:20px;border:1px solid #1F2D45;border-top:none;border-radius:0 0 8px 8px;">
  <div style="color:#666;font-size:10px;text-transform:uppercase;letter-spacing:2px;margin-bottom:12px;">
    {"EMERGENCY ALERT" if is_crash else f"TODAY'S SIGNALS ({len(signals)}件)"}
  </div>
  {main_html}
</div>

<div style="padding:16px;text-align:center;color:#666;font-size:10px;line-height:1.6;">
  運用資金: ¥{TRADING_CONFIG["total_capital"]:,} / 投入率: {TRADING_CONFIG["investment_rate"]*100:.0f}%<br>
  バックテスト実績: 10年勝率63.7%・PF2.87・最大DD36%<br>
  ⚠ 過去データです。将来の利益を保証しません。<br>
  BNF System v6.4.1 - Production Edition
</div>

</div></body></html>'''
    return html

def send_email(subject, html_body):
    if not GMAIL_CONFIG["from_email"] or not GMAIL_CONFIG["app_password"]:
        print("  ⓘ Gmail設定なし → メール送信スキップ（HTMLダッシュボードのみ更新）")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = GMAIL_CONFIG["from_email"]
        msg["To"] = GMAIL_CONFIG["to_email"]
        msg["Date"] = formatdate(localtime=True)
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as smtp:
            smtp.login(GMAIL_CONFIG["from_email"],
                       GMAIL_CONFIG["app_password"].replace(" ",""))
            smtp.send_message(msg)
        print(f"  ✓ 送信成功: {GMAIL_CONFIG['to_email']}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("⚠ 認証エラー！アプリパスワードを確認してください。")
        return False
    except Exception as e:
        print(f"⚠ 送信失敗: {e}")
        return False

def save_html_report(html, is_crash, signals_count):
    """HTMLレポートを public/ フォルダに保存（GitHub Pages用）"""
    os.makedirs("public", exist_ok=True)
    os.makedirs("public/history", exist_ok=True)

    # 最新版（index.html）
    with open("public/index.html", "w", encoding="utf-8") as f:
        f.write(html)

    # 履歴（日付別）
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    with open(f"public/history/{today}.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  ✓ HTMLレポート保存: public/index.html")
    print(f"  ✓ 履歴も保存: public/history/{today}.html")

def run_job():
    now = datetime.datetime.now()
    print(f"\n{'='*60}")
    print(f"  BNF v6.4.1 Daily Scan - {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  監視銘柄: {len(JAPAN_STOCKS)}銘柄")
    print(f"{'='*60}")

    print("\n📊 STEP 1: 暴落判定")
    is_crash, crash_reasons, details = check_crash()
    if is_crash:
        print(f"  🚨 暴落相場と判定")
        for r in crash_reasons:
            print(f"    - {r}")
        signals = []
    else:
        print(f"  ✅ 通常相場")
        print("\n🔍 STEP 2: シグナルスキャン")
        signals = scan_signals()
        print(f"  → {len(signals)}件検出")

    # HTMLを先に生成
    html = build_email_html(is_crash, crash_reasons, details, signals)

    # STEP 3: HTMLダッシュボード保存
    print("\n💾 STEP 3: HTMLダッシュボード保存")
    save_html_report(html, is_crash, len(signals))

    # STEP 4: メール送信（設定があれば）
    print("\n📧 STEP 4: メール送信")
    if is_crash:
        subject = f"🚨 BNF v6.4.1 【暴落警報】{now.strftime('%m/%d')} エントリー禁止"
    else:
        subject = f"🟢 BNF v6.4.1 {now.strftime('%m/%d')} シグナル{len(signals)}件"
    send_email(subject, html)
    print(f"\n{'='*60}\n")

def test_job():
    print("\n🧪 テスト実行\n")
    run_job()

def watch_mode():
    print(f"\n{'='*60}")
    print("  BNF v6.4.1 Watch Mode - 本番運用")
    print(f"{'='*60}")
    print(f"  監視銘柄: {len(JAPAN_STOCKS)}銘柄")
    print(f"  運用資金: ¥{TRADING_CONFIG['total_capital']:,}")
    print(f"  投入率: {TRADING_CONFIG['investment_rate']*100:.0f}%")
    print("  毎朝 08:30 に自動実行します")
    print("  終了するには Ctrl+C")
    print(f"{'='*60}\n")
    for day in ["monday","tuesday","wednesday","thursday","friday"]:
        getattr(schedule.every(), day).at("08:30").do(run_job)
    while True:
        schedule.run_pending()
        time.sleep(30)

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="テスト送信")
    parser.add_argument("--watch", action="store_true", help="毎朝8:30自動実行")
    args = parser.parse_args()

    if args.test:
        test_job()
    elif args.watch:
        watch_mode()
    else:
        run_job()

if __name__ == "__main__":
    main()

# 台股 KD / MACD 單股查詢 App v1

本機 Flask 單頁工具，輸入台股代號後，依官方公開日線資料計算並顯示：

- KD `9,3,3`
- MACD `12,26,9`
- 方向、彎曲、零軸位置
- 第一版滿足點訊號

## 啟動

1. 安裝套件：

```bash
pip install -r requirements.txt
```

2. 啟動：

```bash
flask --app app run
```

3. 開啟瀏覽器：

```text
http://127.0.0.1:5000
```

若要模擬正式環境啟動，可使用：

```bash
gunicorn app:app
```

## API

```text
GET /api/analyze?symbol=6442
```

成功時回傳 JSON 欄位包含：

- `symbol`
- `name`
- `market`
- `dataDate`
- `k` / `d`
- `dif` / `dea` / `osc`
- `kdDirection` / `kdCurve` / `kdSignal`
- `macdDirection` / `macdCurve` / `macdZeroAxis`
- `oscSign`
- `signalSummary`

## 備註

- 上市資料先查 TWSE；查無資料再查 TPEX。
- TPEX 端點同時實作新版與舊版網址，降低官方頁面調整造成的失敗率。
- 第一版 smoke test 建議用 `6442` 做人工比對，重點看方向、交叉與零軸判讀是否一致。

## 穩定版部署建議

若希望每天都能從外網穩定使用，建議部署到正式平台，不要依賴臨時 tunnel。

### Render

- `buildCommand`: `pip install -r requirements.txt`
- `startCommand`: `gunicorn app:app`
- `healthCheckPath`: `/api/health`

專案已附上 [render.yaml](/Users/frank/Documents/Codex/2026-04-27/files-mentioned-by-the-user-2026/render.yaml) 與 [Procfile](/Users/frank/Documents/Codex/2026-04-27/files-mentioned-by-the-user-2026/Procfile)，可直接用於部署。

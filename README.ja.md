# Caldera

[English](README.md) · [Português](README.pt-BR.md) · **日本語**

[Eruption Engine](https://github.com/eruptionlabs/eruption-engine) 用の HUD ビジュアルエディタです。

エンジンの HUD は CSS（`data/hud/default.css`）で記述されています。Caldera はこのファイルを開き、各ウィジェットをエンジンが実際に描画する位置に表示し、マウスで移動・リサイズ・並べ替えができるようにします。エクスポートすると CSS に書き戻され、エンジンは再起動なしで HUD を再読み込みします。

![デフォルト HUD を編集中の Caldera](docs/screenshot.png)

## ゲーム画面と一致する理由

プレビューは単なるモックアップではありません。Caldera はエンジンの `CSSLayout` と同じレイアウト規則を使い、キャラクターを同じカメラ（FOV 60°、ゲーム開始時の距離と角度）と、スプライトシェーダーと同じビルボードで投影します。プレイヤーに追従するウィジェット（`--bind-to-player: 1`）は、どのズームや傾きでも、ゲーム内でスプライトの上に表示される位置と同じ場所に表示されます。

キャンバスは X と Y で同じ倍率を使うため、ウィンドウの縦横比が変わっても HUD が引き伸ばされることはありません。

## 必要なもの

- Python 3.10 以上
- pygame 2.5 以上（`run.sh` が専用の仮想環境にインストールします）
- Eruption Engine のチェックアウト

## 起動方法

エンジン内（サブモジュールとして同梱）の場合：

```bash
git clone --recurse-submodules https://github.com/eruptionlabs/eruption-engine.git
cd eruption-engine
tools/caldera/run.sh
```

エンジンの外で使う場合は、エンジンの場所を指定します：

```bash
ERUPTION_ROOT=/path/to/eruption-engine ./run.sh
```

`ERUPTION_ROOT` を指定しない場合、Caldera は自身のフォルダから上位へたどり、エンジンの `CMakeLists.txt` を探します。

## ウィジェット

| セレクタ | 内容 | 位置の基準 |
|---|---|---|
| `#hero-panel` | 画面下部のパネル | 画面 |
| `#hero-portrait` | ポートレート | パネル |
| `#hero-level` | レベル表示 | パネル |
| `#hero-hp-bar`, `#hero-sp-bar` | HP / SP バー | パネル |
| `#skill-slots`, `#attr-matrix`, `#equip-panel` | ゲーム側で中身を埋めるスロット | パネル |
| `#overhead-hp-sp` | キャラクター頭上の HP / SP | プレイヤー |
| `#cast-bar` | 詠唱バー | プレイヤーまたは画面 |
| `#boss-hp-bar` | ボスの HP バー | 画面 |
| `#minimap`, `#minimap-info` | ミニマップとマップ名の表示 | 画面 |

画面またはパネルを基準とする位置はパーセントで保存されます。プレイヤーに追従するウィジェットは、スプライトの基点からのピクセル数で保存され、カメラのズームに合わせて拡大縮小します。

## 操作方法

| 操作 | 入力 |
|---|---|
| ウィジェットを移動 | ドラッグ |
| リサイズ | 選択中のウィジェットのハンドルをドラッグ |
| 微調整 | 矢印キー（Shift で 10 px ずつ） |
| レイヤーの並べ替え | レイヤーパネルでドラッグ、または Ctrl + PgUp / PgDn |
| プレイヤーへの追従を切り替え | B |
| グリッドにスナップ | G |
| レイヤーパネルの表示 | L |
| レイヤー順のロック | K |
| `default.css` へエクスポート | E、または Export ボタン |
| 選択を解除 | Esc |
| プレビューカメラのズーム | + / −、0 でゲームの初期値に戻す |
| カメラの傾き | [ / ]、P で 50° に戻す |

## 環境変数

| 変数 | 用途 |
|---|---|
| `ERUPTION_ROOT` | Caldera をエンジンの外に置いた場合のエンジンのフォルダ |
| `CALDERA_WINDOW=1600x900` | ウィンドウの初期サイズ |
| `CALDERA_VIRTUAL=1280x720` | エミュレートする画面解像度（初期値 1920x1080） |
| `CALDERA_SCREENSHOT=out.png` | 数フレーム描画して画像を保存し、終了します。エンジンのキャプチャとの比較に便利です |

ゲーム画面と並べて比較するには、HUD 付きでエンジンをキャプチャし、同じ解像度で Caldera を描画します：

```bash
ERUPTION_TEST_SWAP_SHOT=game.png,300 ERUPTION_TEST_EXIT_FRAME=330 ./eruption-engine --map parana_field
CALDERA_VIRTUAL=1280x720 CALDERA_SCREENSHOT=caldera.png tools/caldera/run.sh
```

## オプションの画像

エンジン内に `assets/hud/portrait.png` と `assets/hud/skill_1.png` 〜 `skill_4.png` があれば、プレビューで使用します。ない場合、スロットは空のまま表示されます。キャラクターのスプライトは `assets/sprites/default.spr`（ERUPTSPR 形式）、それがなければ `default.png` から読み込みます。

## ライセンス

Apache License 2.0（Eruption Engine と同じ）です。pygame は LGPL で配布されており、`run.sh` によって別途インストールされます。

「Eruption Engine」とそのロゴは Gdg Soluções Digitais LTDA の商標です。

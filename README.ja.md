# Caldera

[English](README.md) · [Português](README.pt-BR.md) · **日本語**

[Eruption Engine](https://github.com/eruptionlabs/eruption-engine) 用のインターフェース・ビジュアルエディタです。エンジン自身の HUD と、ゲームプロジェクトの任意のインターフェースレイアウトを編集できます。

エンジンの HUD は CSS（`data/hud/default.css`）で、ゲームのメニュー・ターン順・パーティ画面は各ゲーム専用の CSS ファイル（`<プロジェクト>/assets/ui/*.css`）で記述されます。Caldera はそのどれでも開き、各要素をエンジンが実際に描画する位置に表示し、マウスで移動・リサイズ・作成・削除・並べ替えができるようにします。エクスポートすると CSS に書き戻され、エンジンは再起動なしでインターフェースを再読み込みします。

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

### ドキュメントの選び方

```bash
tools/caldera/run.sh                                     # エンジンの HUD（data/hud/default.css）
tools/caldera/run.sh --css path/to/menu.css              # 任意のインターフェース .css
tools/caldera/run.sh --project ~/Documents/my-game       # ゲームプロジェクト（project.eruption のあるフォルダ）
```

| オプション | 動作 |
|---|---|
| `--css ファイル` | その `.css` を開きます。プロジェクト内（上位フォルダに `project.eruption` がある）にあれば、プロジェクトは自動で検出されます。まだ存在しないパスは空のドキュメントとして開き、エクスポート時にだけ作成されます。 |
| `--project フォルダ` | `フォルダ/assets/ui/` の `.css` をタブに並べ、最初のもの（または `--css` で指定したもの）を開きます。画像（`--image`）は `フォルダ` を基準に探します。 |

タブはプログラムを閉じずにドキュメントを切り替え、各タブは未保存の編集を保持します（`*` が目印）。**Open**（Ctrl+O）で任意の `.css` を選べ、**New .css**（Ctrl+N）で空のドキュメントを作れます。未保存の変更があるままウィンドウを閉じると、一度だけ警告します。

## インターフェースの要素

ゲームのインターフェースでは、`#id` のルールがそれぞれ 1 つの要素です。種類はカスタムプロパティ `--widget` で決まります：

| `--widget` | 描画 |
|---|---|
| `rect`（既定） | `background-color`・`border-color`・`border-width`・`border-radius` を持つ矩形 |
| `text` | `content:` の文字列。`color`、`font-size`（画面の高さに対する %、または px）、`text-align` を使用 |
| `bar` | トラック（`background-color`）と、`--value`（0〜1、プレビュー用）の割合で塗る `--fill-color` |
| `image` | `--image: "パス"` の PNG（プロジェクト基準の相対パス）。ファイルがなければ名前入りの破線矩形 |

`--widget` がなければ `rect`（`content` があれば `text`）です。`opacity` は反映され、`display: none` は薄く表示されるので、最初は隠れている要素も編集できます。`content` のない `text`（スクリプトが埋める）や `width`/`height` のない要素は、選択できるように破線の枠と id で示されます。ドラッグしても変わるのは `left`/`top` だけです。

`--parent: #別のid` を指定すると、`left`・`top`・`width`・`height` の % は画面ではなく親の矩形が基準になります。子をドラッグすると、その `left`/`top` が親に対する % で書き換えられ、親を動かすと子も一緒に動きます。自分自身を指す、循環する、存在しない要素を指す `--parent` は無視され、画面に警告が出ます。`--bind-to-player` はこれまでどおり動作し、親は無視されます。

テキストの描画はエンジンに従い、要素の矩形の上端から始まり、その中で揃えられます。フォントはエンジンのものではないため、文字幅は近似です。

## エンジン HUD のウィジェット

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

エンジンの HUD では、上記のウィジェットは独自の描画を保ち、`--parent` がなければ「パネル」と書かれたものは `#hero-panel` の子として扱われます。画面またはパネルを基準とする位置はパーセントで保存されます。プレイヤーに追従するウィジェットは、スプライトの基点からのピクセル数で保存され、カメラのズームに合わせて拡大縮小します。

## 操作方法

| 操作 | 入力 |
|---|---|
| ウィジェットを移動 | ドラッグ（子は親に追従） |
| リサイズ | 選択中のウィジェットのハンドルをドラッグ |
| 微調整 | 矢印キー（Shift で 10 px ずつ） |
| 新しい要素（`--widget` と id を選ぶ） | N、または New |
| 複製 / 削除 | Ctrl + D / Del（削除した要素の子は、画面上の位置を変えずに親へ繰り上がります） |
| id の変更 | F2（それを指していた `--parent` も更新されます） |
| `content` / `--image` の編集 | T |
| 親 / 種類の変更 | R / W |
| レイヤー（`z-index`）の並べ替え | 要素パネル（`z-index` 順、最前面が上）の行をクリック、ドラッグ、Up / Down、または Ctrl + PgUp / PgDn |
| ドキュメントを開く / 新規、次のタブ | Ctrl + O / Ctrl + N、Tab（Shift + Tab で戻る） |
| ディスクから再読み込み | F5（Shift + F5 で未保存の編集を破棄） |
| ショートカット一覧 | F1 |
| プレイヤーへの追従を切り替え | B |
| グリッドにスナップ | G |
| レイヤーパネルの表示 | L |
| レイヤー順のロック | K |
| ドキュメントを保存（エクスポート） | E または Ctrl + S、または Export ボタン |
| 選択を解除 | Esc |
| プレビューカメラのズーム | + / −、0 でゲームの初期値に戻す |
| カメラの傾き | [ / ]、P で 50° に戻す |

## ファイルを壊さずに保存

Caldera はファイルをそのまま保ちます。コメント、空行、ルールの順序、触っていないプロパティの書式は一切変わりません。書き換えられるのは変更したプロパティだけ（その場で）、新しいプロパティはルールの末尾、新しい要素はファイルの末尾に、他と同じ書式（スペース 4 つ、1 行 1 プロパティ）で追加されます。書き込みはアトミックで、まだ存在しないドキュメントはエクスポート時に初めて作成されます。

## 環境変数

| 変数 | 用途 |
|---|---|
| `ERUPTION_ROOT` | Caldera をエンジンの外に置いた場合のエンジンのフォルダ |
| `CALDERA_WINDOW=1600x900` | ウィンドウの初期サイズ |
| `CALDERA_VIRTUAL=1280x720` | エミュレートする画面解像度（初期値 1920x1080） |
| `CALDERA_SCREENSHOT=out.png` | 数フレーム描画して画像を保存し、終了します。エンジンのキャプチャとの比較に便利です |

ゲーム画面と並べて比較するには、HUD 付きでエンジンをキャプチャし、同じ解像度で Caldera を描画します：

```bash
ERUPTION_TEST_SWAP_SHOT=game.png,300 ERUPTION_TEST_EXIT_FRAME=330 ./eruption-engine --project projects/parana_field --map parana_field_lite
CALDERA_VIRTUAL=1280x720 CALDERA_SCREENSHOT=caldera.png tools/caldera/run.sh
```

## オプションの画像

エンジン内に `assets/hud/portrait.png` と `assets/hud/skill_1.png` 〜 `skill_4.png` があれば、プレビューで使用します。ない場合、スロットは空のまま表示されます。キャラクターのスプライトは `assets/sprites/default.spr`（ERUPTSPR 形式）、それがなければ `default.png` から読み込みます。

## ライセンス

Apache License 2.0（Eruption Engine と同じ）です。pygame は LGPL で配布されており、`run.sh` によって別途インストールされます。

「Eruption Engine」とそのロゴは Gdg Soluções Digitais LTDA の商標です。

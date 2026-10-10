# Caldera

[English](README.md) · **Português** · [日本語](README.ja.md)

Editor visual de interface da [Eruption Engine](https://github.com/eruptionlabs/eruption-engine): a HUD da própria engine e qualquer layout de interface de um projeto de jogo.

A HUD da engine é descrita em CSS (`data/hud/default.css`), e um jogo descreve seus menus, fila de turnos e ficha da party em arquivos CSS próprios (`<projeto>/assets/ui/*.css`). O Caldera abre qualquer um desses arquivos, desenha cada elemento no lugar em que a engine vai desenhar, e deixa você mover, redimensionar, criar, apagar e reordenar tudo com o mouse. Ao exportar, ele grava o CSS de volta e a engine recarrega a interface sem precisar reiniciar.

![Caldera editando a HUD padrão](docs/screenshot.png)

## Por que ele é fiel ao jogo

O preview não é um mockup. O Caldera usa as mesmas regras de layout do `CSSLayout` da engine e projeta o personagem com a mesma câmera (FOV 60°, distância e pitch iniciais do jogo) e o mesmo billboard do shader de sprites. Widgets presos ao jogador (`--bind-to-player: 1`) aparecem exatamente onde vão aparecer em cima do sprite, em qualquer zoom e inclinação.

A escala do canvas é igual em X e Y, então a janela pode ter qualquer proporção sem esticar a HUD.

## Requisitos

- Python 3.10 ou mais novo
- pygame 2.5 ou mais novo (o `run.sh` instala num ambiente virtual próprio)
- Um checkout da Eruption Engine

## Como rodar

Dentro da engine, onde ele já vem como submódulo:

```bash
git clone --recurse-submodules https://github.com/eruptionlabs/eruption-engine.git
cd eruption-engine
tools/caldera/run.sh
```

Fora da engine, aponte para ela:

```bash
ERUPTION_ROOT=/caminho/da/eruption-engine ./run.sh
```

Sem `ERUPTION_ROOT`, o Caldera sobe as pastas a partir de onde está até achar o `CMakeLists.txt` da engine.

### Escolhendo o documento

```bash
tools/caldera/run.sh                                     # a HUD da engine (data/hud/default.css)
tools/caldera/run.sh --css caminho/para/menu.css         # qualquer .css de interface
tools/caldera/run.sh --project ~/Documentos/meu-jogo     # o projeto de jogo (pasta com project.eruption)
```

| Opção | O que faz |
|---|---|
| `--css ARQUIVO` | Abre esse `.css`. Se ele estiver dentro de um projeto (alguma pasta acima tem `project.eruption`), o projeto é detectado sozinho. Um caminho que ainda não existe começa um documento vazio, gravado só quando você exportar. |
| `--project PASTA` | Lista os `.css` de `PASTA/assets/ui/` em abas e abre o primeiro (ou o dado em `--css`). As imagens (`--image`) são procuradas a partir de `PASTA`. |

As abas trocam de documento sem fechar o programa, e cada aba guarda as alterações ainda não gravadas (um `*` marca). **Open** (Ctrl+O) procura qualquer `.css`; **New .css** (Ctrl+N) começa um vazio. Fechar a janela com alterações não gravadas avisa uma vez antes.

## Elementos de uma interface

Numa interface de jogo, cada regra de `#id` é um elemento. O tipo vem da propriedade customizada `--widget`:

| `--widget` | Desenha |
|---|---|
| `rect` (padrão) | retângulo com `background-color`, `border-color`, `border-width`, `border-radius` |
| `text` | a string de `content:`, com `color`, `font-size` (% da ALTURA da tela, ou px) e `text-align` |
| `bar` | trilho (`background-color`) e preenchimento (`--fill-color`) na proporção de `--value` (0 a 1, só para a prévia) |
| `image` | o PNG de `--image: "caminho"`, relativo ao projeto. Se o arquivo não existir, um retângulo tracejado com o nome |

Sem `--widget`, o elemento é um `rect` (ou um `text`, se tiver `content`). `opacity` é aplicada; `display: none` aparece esmaecido, para você continuar editando o que começa escondido. Um `text` sem `content` (o script preenche) ou sem `width`/`height` é marcado com uma caixa tracejada e o id, para dar para selecionar; arrastá-lo só muda `left`/`top`.

`--parent: #outro-id` faz `left`, `top`, `width` e `height` valerem em % do retângulo do pai, não da tela. Arrastar um filho reescreve o `left`/`top` dele em % do pai, e mover o pai leva os filhos junto. Um `--parent` que aponta para si mesmo, forma um ciclo ou cita um elemento que não existe é ignorado e avisado na tela. O `--bind-to-player` continua funcionando como antes e ignora o pai.

O texto segue o desenho da engine: começa no topo do retângulo do elemento e se alinha dentro dele. A fonte não é a da engine, então a largura do texto é aproximada.

## Widgets da HUD da engine

| Seletor | O que é | Posição relativa a |
|---|---|---|
| `#hero-panel` | Painel inferior | tela |
| `#hero-portrait` | Retrato | painel |
| `#hero-level` | Selo de nível | painel |
| `#hero-hp-bar`, `#hero-sp-bar` | Barras de HP e SP | painel |
| `#skill-slots`, `#attr-matrix`, `#equip-panel` | Slots que o jogo preenche | painel |
| `#overhead-hp-sp` | HP e SP sobre o personagem | jogador |
| `#cast-bar` | Barra de conjuração | jogador ou tela |
| `#boss-hp-bar` | Barra de chefe | tela |
| `#minimap`, `#minimap-info` | Minimapa e caixa de nome do mapa | tela |

Na HUD da engine os widgets acima mantêm o desenho próprio e, sem `--parent`, os marcados como "painel" são filhos do `#hero-panel`. Posições relativas à tela ou ao painel são salvas em porcentagem. Widgets presos ao jogador são salvos em pixels a partir da base do sprite e escalam com o zoom da câmera.

## Controles

| Ação | Como |
|---|---|
| Mover um widget | arrastar (os filhos acompanham o pai) |
| Redimensionar | arrastar as alças do widget selecionado |
| Ajuste fino | setas (Shift move 10 px) |
| Novo elemento (escolhe `--widget` e id) | N, ou New |
| Duplicar / apagar | Ctrl + D / Del (os filhos de um elemento apagado sobem para o pai dele sem sair do lugar) |
| Renomear o id | F2 (os `--parent` que apontavam para ele são atualizados) |
| Editar `content` / `--image` | T |
| Trocar o pai / o tipo | R / W |
| Reordenar camadas (`z-index`) | clicar numa linha do painel de elementos (ordenado por `z-index`, o de cima primeiro), arrastar, usar Up / Down, ou Ctrl + PgUp / PgDn |
| Abrir / novo documento, próxima aba | Ctrl + O / Ctrl + N, Tab (Shift + Tab volta) |
| Recarregar do disco | F5 (Shift + F5 descarta o que não foi gravado) |
| Lista de atalhos | F1 |
| Prender ou soltar do jogador | B |
| Snap à grade | G |
| Painel de camadas | L |
| Travar ordem das camadas | K |
| Gravar o documento (exportar) | E ou Ctrl + S, ou o botão Export |
| Limpar seleção | Esc |
| Zoom da câmera do preview | + e −, 0 volta ao padrão do jogo |
| Inclinação da câmera | [ e ], P volta a 50° |

## Gravar sem estragar o seu arquivo

O Caldera preserva o arquivo como estava: comentários, linhas em branco, a ordem das regras e a formatação de toda propriedade que você não tocou ficam idênticos. Só as propriedades que mudaram são reescritas (no lugar), propriedades novas entram no fim da regra, e elementos novos entram no fim do arquivo, no mesmo formato dos outros (4 espaços, uma propriedade por linha). A gravação é atômica, e um documento que ainda não existe só é criado quando você exporta.

## Variáveis de ambiente

| Variável | Uso |
|---|---|
| `ERUPTION_ROOT` | Pasta da engine, quando o Caldera está fora dela |
| `CALDERA_WINDOW=1600x900` | Tamanho inicial da janela |
| `CALDERA_VIRTUAL=1280x720` | Resolução de tela emulada (padrão 1920x1080) |
| `CALDERA_SCREENSHOT=saida.png` | Renderiza alguns quadros, salva a imagem e sai. Útil para comparar com uma captura da engine |

Para comparar com o jogo lado a lado, capture a engine com a HUD e renderize o Caldera na mesma resolução:

```bash
ERUPTION_TEST_SWAP_SHOT=jogo.png,300 ERUPTION_TEST_EXIT_FRAME=330 ./eruption-engine --map parana_field
CALDERA_VIRTUAL=1280x720 CALDERA_SCREENSHOT=caldera.png tools/caldera/run.sh
```

## Imagens opcionais

Se existirem na engine, o preview usa `assets/hud/portrait.png` e `assets/hud/skill_1.png` a `skill_4.png`. Sem elas, os slots aparecem vazios. O sprite do personagem vem de `assets/sprites/default.spr` (formato ERUPTSPR) ou, na falta dele, de `default.png`.

## Licença

Apache License 2.0, a mesma da Eruption Engine. O pygame é distribuído sob a LGPL e é instalado à parte pelo `run.sh`.

"Eruption Engine" e o logotipo são marcas da Gdg Soluções Digitais LTDA.

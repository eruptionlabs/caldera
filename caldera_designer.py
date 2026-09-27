#!/usr/bin/env python3
"""
Caldera HUD Designer - Editor visual de layout responsivo para Eruption Engine.

Renderiza a HUD como a engine a desenha: lê data/hud/default.css, resolve
posições/tamanhos igual ao CSSLayout C++ (src/utils/CSSLayout.cpp) e pinta
cores, bordas, clip-paths, barras e slots. O personagem do preview é projetado
com a mesma câmera e o mesmo billboard da engine, então widgets presos ao
jogador (--bind-to-player) ficam onde ficariam no jogo.

Regras de coordenadas (igual ao engine):
- #boss-hp-bar, #hero-panel, #minimap: coordenadas em % da tela.
- Todos os demais editáveis: coordenadas em % do #hero-panel.
"""

import pygame
import sys
import os
import re
import math
from datetime import datetime

def _find_engine_root():
    """Raiz da Eruption Engine: ERUPTION_ROOT, ou o primeiro ancestral com CMakeLists.txt."""
    env = os.environ.get('ERUPTION_ROOT')
    if env:
        return os.path.abspath(env)
    here = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.exists(os.path.join(here, 'CMakeLists.txt')):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            return os.getcwd()
        here = parent

BASE_DIR = _find_engine_root()
HUD_CSS_FILE = os.path.join(BASE_DIR, 'data', 'hud', 'default.css')
ASSETS_DIR = os.path.join(BASE_DIR, 'assets')

# Resolução virtual de referência (16:9).
# Resolucao da tela emulada. CALDERA_VIRTUAL="1280x720" troca (ex.: para bater
# com uma captura da engine em janela 1280x720; widgets em px nao escalam).
VIRTUAL_WIDTH = 1920.0
VIRTUAL_HEIGHT = 1080.0
if os.environ.get('CALDERA_VIRTUAL'):
    try:
        _vw, _vh = os.environ['CALDERA_VIRTUAL'].lower().split('x')
        VIRTUAL_WIDTH, VIRTUAL_HEIGHT = float(_vw), float(_vh)
    except ValueError:
        pass

# ---------------------------------------------------------------------------
# Projeção do placeholder do personagem (igual à Eruption Engine)
# ---------------------------------------------------------------------------
# A engine projeta o personagem no mundo 3D e usa o ponto BASE (centro do
# corpo, aproximadamente 40 % da altura do sprite a partir do chão) como
# âncora para widgets bind-to-player. O Caldera reproduz a mesma projeção
# para que o preview seja fiel ao que o jogador vê.
PLAYER_SPRITE_HEIGHT_WORLD = 14.18   # altura do sprite no espaço do mundo
PLAYER_CAMERA_FOV = math.radians(60.0)
PLAYER_CAMERA_PITCH_DEG = 50.0   # pitch editável pelo usuário
PLAYER_CAMERA_YAW = math.radians(-90.0)   # m_yaw usado pela CombatCamera
PLAYER_CAMERA_DISTANCE = 158.5


def _vec3_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec3_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _vec3_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec3_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _vec3_scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _vec3_len(a):
    return math.sqrt(_vec3_dot(a, a))


def _vec3_norm(a):
    l = _vec3_len(a)
    if l == 0.0:
        return a
    return _vec3_scale(a, 1.0 / l)


def _look_at(eye, center, up):
    """Matriz view estilo GLM (row-major, multiplicada à esquerda)."""
    f = _vec3_norm(_vec3_sub(center, eye))
    s = _vec3_norm(_vec3_cross(f, up))
    u = _vec3_cross(s, f)
    return [
        [s[0], s[1], s[2], -_vec3_dot(s, eye)],
        [u[0], u[1], u[2], -_vec3_dot(u, eye)],
        [-f[0], -f[1], -f[2], _vec3_dot(f, eye)],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _perspective_vulkan(fov_y, aspect, near, far):
    """Projeção perspectiva com Y invertido (Vulkan / Eruption)."""
    f = 1.0 / math.tan(fov_y * 0.5)
    return [
        [f / aspect, 0.0, 0.0, 0.0],
        [0.0, -f, 0.0, 0.0],
        [0.0, 0.0, far / (near - far), (far * near) / (near - far)],
        [0.0, 0.0, -1.0, 0.0],
    ]


def _mat4_mul_vec(m, v):
    return tuple(sum(m[i][j] * v[j] for j in range(4)) for i in range(4))


def _mat4_mul(a, b):
    r = [[0.0] * 4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            acc = 0.0
            for k in range(4):
                acc += a[i][k] * b[k][j]
            r[i][j] = acc
    return r


def _transform_point(m, p):
    x = m[0][0] * p[0] + m[0][1] * p[1] + m[0][2] * p[2] + m[0][3]
    y = m[1][0] * p[0] + m[1][1] * p[1] + m[1][2] * p[2] + m[1][3]
    z = m[2][0] * p[0] + m[2][1] * p[1] + m[2][2] * p[2] + m[2][3]
    w = m[3][0] * p[0] + m[3][1] * p[1] + m[3][2] * p[2] + m[3][3]
    return (x / w, y / w, z / w)


def _project_world_to_screen(point, width, height, view, proj):
    clip = _transform_point(_mat4_mul(proj, view), point)
    return (
        (clip[0] * 0.5 + 0.5) * width,
        (clip[1] * 0.5 + 0.5) * height,
    )


def _compute_player_projection(distance_ratio=1.0):
    """Retorna (centro_visual, base, altura_em_pixels, zoom_scale).

    distance_ratio = orbitDistance / defaultOrbitDistance.  Na engine:
        zoomScale = defaultOrbitDistance / orbitDistance = 1 / distance_ratio.
    """
    sprite_h = PLAYER_SPRITE_HEIGHT_WORLD
    zoom_scale = 1.0 / distance_ratio

    # yaw usado pela câmera da engine = m_yaw + 90
    yaw = PLAYER_CAMERA_YAW + math.radians(90.0)
    pitch = math.radians(PLAYER_CAMERA_PITCH_DEG)
    distance = PLAYER_CAMERA_DISTANCE * distance_ratio

    target = (0.0, sprite_h * 0.5, 0.0)
    eye = (
        target[0] - distance * math.cos(pitch) * math.cos(yaw),
        target[1] + distance * math.sin(pitch),
        target[2] + distance * math.cos(pitch) * math.sin(yaw),
    )
    up = (0.0, 1.0, 0.0)

    view = _look_at(eye, target, up)
    proj = _perspective_vulkan(
        PLAYER_CAMERA_FOV,
        VIRTUAL_WIDTH / VIRTUAL_HEIGHT,
        0.1,
        50000.0,
    )

    center = _project_world_to_screen(
        (0.0, sprite_h * 0.5, 0.0), VIRTUAL_WIDTH, VIRTUAL_HEIGHT, view, proj
    )
    base = _project_world_to_screen(
        (0.0, sprite_h * 0.4, 0.0), VIRTUAL_WIDTH, VIRTUAL_HEIGHT, view, proj
    )
    top = _project_world_to_screen(
        (0.0, sprite_h, 0.0), VIRTUAL_WIDTH, VIRTUAL_HEIGHT, view, proj
    )
    bottom = _project_world_to_screen(
        (0.0, 0.0, 0.0), VIRTUAL_WIDTH, VIRTUAL_HEIGHT, view, proj
    )

    # A engine desenha o sprite como BILLBOARD no plano da camera (sprite.vert:
    # localPos = viewUp * y no espaco de vista), entao a altura na tela nao
    # depende do pitch: h_px = h * f / profundidade * (altura_tela / 2), com
    # f = 1 / tan(fov/2) e profundidade = z de vista dos pes. O quad sobe dos
    # pes (project(0)) verticalmente na tela. Medido na engine a 1280x720,
    # zoom 85%%, pitch 50: pes y=388.9, quad 93.7 px - esta conta reproduz isso.
    feet_view = _mat4_mul_vec(view, (0.0, 0.0, 0.0, 1.0))
    depth = max(1e-3, -feet_view[2])
    f = 1.0 / math.tan(PLAYER_CAMERA_FOV * 0.5)
    screen_h = sprite_h * f / depth * (VIRTUAL_HEIGHT * 0.5)
    center = (bottom[0], bottom[1] - screen_h * 0.5)
    return center, base, screen_h, zoom_scale


def _get_player_view_proj(distance_ratio=None, pitch_deg=None, target_height=None):
    """Retorna (view, proj) do preview do Caldera.

    distance_ratio: orbitDistance / defaultOrbitDistance (1.0 = zoom default).
    pitch_deg: ângulo de pitch em graus; se None usa PLAYER_CAMERA_PITCH_DEG.
    target_height: altura do alvo da câmera; padrão = centro do sprite.
    """
    if distance_ratio is None:
        distance_ratio = PLAYER_CAMERA_ZOOM
    if pitch_deg is None:
        pitch_deg = PLAYER_CAMERA_PITCH_DEG
    if target_height is None:
        target_height = PLAYER_SPRITE_HEIGHT_WORLD * 0.5
    sprite_h = PLAYER_SPRITE_HEIGHT_WORLD
    yaw = PLAYER_CAMERA_YAW + math.radians(90.0)
    pitch = math.radians(pitch_deg)
    distance = PLAYER_CAMERA_DISTANCE * distance_ratio
    target = (0.0, target_height, 0.0)
    eye = (
        target[0] - distance * math.cos(pitch) * math.cos(yaw),
        target[1] + distance * math.sin(pitch),
        target[2] + distance * math.cos(pitch) * math.sin(yaw),
    )
    up = (0.0, 1.0, 0.0)
    view = _look_at(eye, target, up)
    proj = _perspective_vulkan(
        PLAYER_CAMERA_FOV,
        VIRTUAL_WIDTH / VIRTUAL_HEIGHT,
        0.1,
        50000.0,
    )
    return view, proj


def _get_camera_up_world(distance_ratio=None, pitch_deg=None):
    """Retorna o vetor 'up' da câmera no espaço do mundo (aponta para o topo da tela)."""
    if distance_ratio is None:
        distance_ratio = PLAYER_CAMERA_ZOOM
    if pitch_deg is None:
        pitch_deg = PLAYER_CAMERA_PITCH_DEG
    sprite_h = PLAYER_SPRITE_HEIGHT_WORLD
    yaw = PLAYER_CAMERA_YAW + math.radians(90.0)
    pitch = math.radians(pitch_deg)
    distance = PLAYER_CAMERA_DISTANCE * distance_ratio
    target = (0.0, sprite_h * 0.5, 0.0)
    eye = (
        target[0] - distance * math.cos(pitch) * math.cos(yaw),
        target[1] + distance * math.sin(pitch),
        target[2] + distance * math.cos(pitch) * math.sin(yaw),
    )
    f = _vec3_norm(_vec3_sub(target, eye))
    s = _vec3_norm(_vec3_cross(f, (0.0, 1.0, 0.0)))
    u = _vec3_cross(s, f)
    return u


def _mat4_inverse(m):
    """Inverte uma matriz 4x4 (GL style)."""
    inv = [[0.0] * 4 for _ in range(4)]
    inv[0][0] = (m[1][1] * (m[2][2] * m[3][3] - m[2][3] * m[3][2]) -
                 m[1][2] * (m[2][1] * m[3][3] - m[2][3] * m[3][1]) +
                 m[1][3] * (m[2][1] * m[3][2] - m[2][2] * m[3][1]))
    inv[0][1] = -(m[0][1] * (m[2][2] * m[3][3] - m[2][3] * m[3][2]) -
                  m[0][2] * (m[2][1] * m[3][3] - m[2][3] * m[3][1]) +
                  m[0][3] * (m[2][1] * m[3][2] - m[2][2] * m[3][1]))
    inv[0][2] = (m[0][1] * (m[1][2] * m[3][3] - m[1][3] * m[3][2]) -
                 m[0][2] * (m[1][1] * m[3][3] - m[1][3] * m[3][1]) +
                 m[0][3] * (m[1][1] * m[3][2] - m[1][2] * m[3][1]))
    inv[0][3] = -(m[0][1] * (m[1][2] * m[2][3] - m[1][3] * m[2][2]) -
                  m[0][2] * (m[1][1] * m[2][3] - m[1][3] * m[2][1]) +
                  m[0][3] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]))

    inv[1][0] = -(m[1][0] * (m[2][2] * m[3][3] - m[2][3] * m[3][2]) -
                  m[1][2] * (m[2][0] * m[3][3] - m[2][3] * m[3][0]) +
                  m[1][3] * (m[2][0] * m[3][2] - m[2][2] * m[3][0]))
    inv[1][1] = (m[0][0] * (m[2][2] * m[3][3] - m[2][3] * m[3][2]) -
                 m[0][2] * (m[2][0] * m[3][3] - m[2][3] * m[3][0]) +
                 m[0][3] * (m[2][0] * m[3][2] - m[2][2] * m[3][0]))
    inv[1][2] = -(m[0][0] * (m[1][2] * m[3][3] - m[1][3] * m[3][2]) -
                  m[0][2] * (m[1][0] * m[3][3] - m[1][3] * m[3][0]) +
                  m[0][3] * (m[1][0] * m[3][2] - m[1][2] * m[3][0]))
    inv[1][3] = (m[0][0] * (m[1][2] * m[2][3] - m[1][3] * m[2][2]) -
                 m[0][2] * (m[1][0] * m[2][3] - m[1][3] * m[2][0]) +
                 m[0][3] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]))

    inv[2][0] = (m[1][0] * (m[2][1] * m[3][3] - m[2][3] * m[3][1]) -
                 m[1][1] * (m[2][0] * m[3][3] - m[2][3] * m[3][0]) +
                 m[1][3] * (m[2][0] * m[3][1] - m[2][1] * m[3][0]))
    inv[2][1] = -(m[0][0] * (m[2][1] * m[3][3] - m[2][3] * m[3][1]) -
                  m[0][1] * (m[2][0] * m[3][3] - m[2][3] * m[3][0]) +
                  m[0][3] * (m[2][0] * m[3][1] - m[2][1] * m[3][0]))
    inv[2][2] = (m[0][0] * (m[1][1] * m[3][3] - m[1][3] * m[3][1]) -
                 m[0][1] * (m[1][0] * m[3][3] - m[1][3] * m[3][0]) +
                 m[0][3] * (m[1][0] * m[3][1] - m[1][1] * m[3][0]))
    inv[2][3] = -(m[0][0] * (m[1][1] * m[2][3] - m[1][3] * m[2][1]) -
                  m[0][1] * (m[1][0] * m[2][3] - m[1][3] * m[2][0]) +
                  m[0][3] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))

    inv[3][0] = -(m[1][0] * (m[2][1] * m[3][2] - m[2][2] * m[3][1]) -
                  m[1][1] * (m[2][0] * m[3][2] - m[2][2] * m[3][0]) +
                  m[1][2] * (m[2][0] * m[3][1] - m[2][1] * m[3][0]))
    inv[3][1] = (m[0][0] * (m[2][1] * m[3][2] - m[2][2] * m[3][1]) -
                 m[0][1] * (m[2][0] * m[3][2] - m[2][2] * m[3][0]) +
                 m[0][2] * (m[2][0] * m[3][1] - m[2][1] * m[3][0]))
    inv[3][2] = -(m[0][0] * (m[1][1] * m[3][2] - m[1][2] * m[3][1]) -
                  m[0][1] * (m[1][0] * m[3][2] - m[1][2] * m[3][0]) +
                  m[0][2] * (m[1][0] * m[3][1] - m[1][1] * m[3][0]))
    inv[3][3] = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) -
                 m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) +
                 m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))

    det = (m[0][0] * inv[0][0] + m[0][1] * inv[1][0] +
           m[0][2] * inv[2][0] + m[0][3] * inv[3][0])
    if abs(det) < 1e-10:
        return None
    inv_det = 1.0 / det
    for i in range(4):
        for j in range(4):
            inv[i][j] *= inv_det
    return inv


def _screen_to_world_ground(screen_x, screen_y, width, height, view, proj):
    """Raycast tela -> plano do chão (y=0) usando a matriz view/proj atuais."""
    ndc_x = (screen_x / width) * 2.0 - 1.0
    ndc_y = (screen_y / height) * 2.0 - 1.0
    vp = _mat4_mul(proj, view)
    inv_vp = _mat4_inverse(vp)
    if inv_vp is None:
        return None

    def unproject(ndc_z):
        return _transform_point(inv_vp, (ndc_x, ndc_y, ndc_z, 1.0))

    near = unproject(0.0)
    far = unproject(1.0)
    dx = far[0] - near[0]
    dy = far[1] - near[1]
    dz = far[2] - near[2]
    if abs(dy) < 1e-7:
        return None
    t = -near[1] / dy
    return (near[0] + dx * t, near[1] + dy * t, near[2] + dz * t)


# Estado da projeção do player.  Pode ser alterado em tempo de execução para
# refletir o zoom da câmera da engine.
PLAYER_CAMERA_ZOOM = 1.0   # distance_ratio (1.0 = distância default)


def recalc_player_projection(distance_ratio=PLAYER_CAMERA_ZOOM):
    """Recalcula PLAYER_CENTER / PLAYER_BASE / PLAYER_SPRITE_H / PLAYER_ZOOM_SCALE.

    Deve ser chamada quando o zoom da câmera muda.
    """
    global PLAYER_CENTER, PLAYER_BASE, PLAYER_SPRITE_H, PLAYER_POS, PLAYER_ZOOM_SCALE, PLAYER_CAMERA_ZOOM
    PLAYER_CENTER, PLAYER_BASE, PLAYER_SPRITE_H, PLAYER_ZOOM_SCALE = _compute_player_projection(distance_ratio)
    PLAYER_CAMERA_ZOOM = distance_ratio
    PLAYER_POS = PLAYER_BASE


recalc_player_projection()

# Componentes editáveis: (nome amigável, seletor, é top-level?)
EDITABLE_COMPONENTS = [
    ("Boss HP",        "#boss-hp-bar",    True),
    ("Hero Panel",     "#hero-panel",     True),
    ("Portrait",       "#hero-portrait",  False),
    ("Level",          "#hero-level",     False),
    ("Attributes",     "#attr-matrix",    False),
    ("HP Bar",         "#hero-hp-bar",    False),
    ("SP Bar",         "#hero-sp-bar",    False),
    ("Equipment",      "#equip-panel",    False),
    ("Skills",         "#skill-slots",    False),
    ("Minimap",        "#minimap",        True),
    ("Minimap Info",   "#minimap-info",   True),
    ("Cast Bar",       "#cast-bar",       True),
    ("Overhead HP/SP", "#overhead-hp-sp", True),
]

# Propriedades gerenciadas pelo designer.
LAYOUT_PROPS = {"position", "left", "top", "right", "bottom", "width", "height", "z-index"}


def parse_percent(value):
    if value is None:
        return None
    v = value.strip()
    if v.endswith('%'):
        try:
            return float(v[:-1]) / 100.0
        except ValueError:
            return None
    return None


def parse_length(value, base):
    if value is None:
        return None
    v = value.strip().lower()
    if v.endswith('%'):
        try:
            return float(v[:-1]) * base / 100.0
        except ValueError:
            return None
    elif v.endswith('px'):
        try:
            return float(v[:-2])
        except ValueError:
            return None
    else:
        try:
            return float(v)
        except ValueError:
            return None


def to_percent_str(ratio):
    return f"{ratio * 100.0:.3f}%"


def hex_to_rgba(value):
    """Converte #rgb/#rgba/#rrggbb/#rrggbbaa para (r,g,b,a)."""
    v = value.strip().lower()
    if not v.startswith('#'):
        return None
    h = v[1:]
    if len(h) == 3:
        r = int(h[0] * 2, 16)
        g = int(h[1] * 2, 16)
        b = int(h[2] * 2, 16)
        return (r, g, b, 255)
    if len(h) == 4:
        r = int(h[0] * 2, 16)
        g = int(h[1] * 2, 16)
        b = int(h[2] * 2, 16)
        a = int(h[3] * 2, 16)
        return (r, g, b, a)
    if len(h) == 6:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
    if len(h) == 8:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
    return None


def parse_color(value, fallback=(255, 255, 255, 255)):
    rgba = hex_to_rgba(value) if value else None
    return rgba if rgba else fallback


def shade_color(rgba, f):
    return (
        min(255, max(0, int(rgba[0] * f))),
        min(255, max(0, int(rgba[1] * f))),
        min(255, max(0, int(rgba[2] * f))),
        rgba[3]
    )


def alpha_color(rgba, a):
    return (rgba[0], rgba[1], rgba[2], a)


def lerp_color(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


class CSSRule:
    def __init__(self, selector, properties, raw_text=""):
        self.selector = selector
        self.properties = properties
        self.raw_text = raw_text


# ---------------------------------------------------------------------------
# Preview do heroi: PNG estatico (assets/portraits). Sem parser de sprite.
# ---------------------------------------------------------------------------
class HeroPreview:
    """Imagem do heroi usada no preview. Le ERUPTSPR (formato nativo da engine,
    src/formats/SpriteParser.cpp) quando existe <stem>.spr, senao o PNG - a
    mesma ordem de preferencia do PlayerController."""
    def __init__(self):
        self.surface = None
        self.scale_y = 2.0   # pngScale da engine para PNG; lido do .spr quando ERUPTSPR

    @staticmethod
    def _load_eruptspr(path):
        import struct
        with open(path, 'rb') as f:
            data = f.read()
        if len(data) < 28 or data[:8] != b'ERUPTSPR':
            return None, 2.0
        version, w, h, ch = struct.unpack_from('<4I', data, 8)
        if version != 1 or ch != 4 or w == 0 or h == 0:
            return None, 2.0
        pos = 24
        pixels = bytearray(data[pos:pos + w * h * 4]); pos += w * h * 4
        # alpha com corte duro em 128, igual ao SpriteParser da engine
        for i in range(0, len(pixels), 4):
            if pixels[i + 3] < 128:
                pixels[i:i + 4] = b'\x00\x00\x00\x00'
            else:
                pixels[i + 3] = 255
        surf = pygame.image.frombuffer(bytes(pixels), (w, h), 'RGBA').convert_alpha()
        scale_y = 2.0
        try:
            dir_count, action_count = struct.unpack_from('<2I', data, pos); pos += 8
            frames_per_dir = struct.unpack_from('<I', data, pos)[0]; pos += 4
            sprite_count = struct.unpack_from('<I', data, pos)[0]; pos += 4
            _idx, _ox, _oy, _sx, scale_y = struct.unpack_from('<Iiiff', data, pos)
        except struct.error:
            pass
        return surf, scale_y

    def load(self, path):
        """path sem extensao (ex.: assets/sprites/default) ou com .png/.spr."""
        stem = path[:-4] if path.lower().endswith(('.png', '.spr')) else path
        self.surface = None
        try:
            if os.path.exists(stem + '.spr'):
                self.surface, self.scale_y = self._load_eruptspr(stem + '.spr')
            if self.surface is None and os.path.exists(stem + '.png'):
                self.surface = pygame.image.load(stem + '.png').convert_alpha()
                self.scale_y = 2.0
        except Exception:
            self.surface = None
        if self.surface is not None:
            # Engine (renderSpritePart): quad = altura_px x 0.15 x scaleY no mundo,
            # base nos pes, ancora dos widgets a 40% dessa altura.
            global PLAYER_SPRITE_HEIGHT_WORLD
            PLAYER_SPRITE_HEIGHT_WORLD = self.surface.get_height() * 0.15 * self.scale_y
            recalc_player_projection(PLAYER_CAMERA_ZOOM)
        return self.surface is not None


class CSSDocument:
    """Parser/serializer CSS simples que preserva comentários e regras não editáveis."""

    def __init__(self, path):
        self.path = path
        self.rules = {}
        self.raw_blocks = []
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            with open(self.path, 'w', encoding='utf-8') as f:
                f.write("/* Eruption Engine HUD */\n\n")
            return
        with open(self.path, 'r', encoding='utf-8') as f:
            content = f.read()
        pattern = r'(/\*.*?\*/|\s*([^{}/\s][^{}]*)\s*\{[^}]*\})'
        pos = 0
        for m in re.finditer(pattern, content, re.DOTALL):
            if m.start() > pos:
                self.raw_blocks.append((None, content[pos:m.start()]))
            block = m.group(0)
            selector = m.group(2)
            if selector:
                selector = selector.strip()
                props = self._parse_props(block)
                self.rules[selector] = CSSRule(selector, props, block)
                self.raw_blocks.append((selector, block))
            else:
                self.raw_blocks.append((None, block))
            pos = m.end()
        if pos < len(content):
            self.raw_blocks.append((None, content[pos:]))

    def _parse_props(self, block):
        props = {}
        inner = block[block.find('{') + 1:block.rfind('}')]
        for line in inner.split(';'):
            if ':' not in line:
                continue
            key, val = line.split(':', 1)
            key = key.strip()
            val = val.strip()
            if key:
                props[key] = val
        return props

    def get_prop(self, selector, prop):
        rule = self.rules.get(selector)
        if not rule:
            return None
        return rule.properties.get(prop)

    def set_prop(self, selector, prop, value):
        rule = self.rules.get(selector)
        if not rule:
            return
        if value is None:
            rule.properties.pop(prop, None)
        else:
            rule.properties[prop] = value

    def get_block_text(self, selector):
        rule = self.rules.get(selector)
        if not rule:
            return ""
        lines = [f"{selector} {{"]
        for key, val in rule.properties.items():
            lines.append(f"    {key}: {val};")
        lines.append("}")
        return "\n".join(lines)

    def write(self):
        parts = []
        seen = set()
        for selector, text in self.raw_blocks:
            if selector is None:
                parts.append(text)
            else:
                if selector in seen:
                    continue
                seen.add(selector)
                if parts and not parts[-1].endswith('\n'):
                    parts.append('\n')
                parts.append(self.get_block_text(selector))
                parts.append('\n')
        for name, selector, _ in EDITABLE_COMPONENTS:
            if selector not in seen and selector in self.rules:
                parts.append("\n" + self.get_block_text(selector) + "\n")
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write("".join(parts))


class CSSResolver:
    """Resolve posições de tela a partir das regras CSS, imitando o engine C++."""

    def __init__(self, doc):
        self.doc = doc

    def _get_pct(self, selector, prop, base):
        val = self.doc.get_prop(selector, prop)
        if val is None:
            return None
        return parse_length(val, base)

    def resolve(self, selector, display_w=VIRTUAL_WIDTH, display_h=VIRTUAL_HEIGHT, _hero=None):
        is_top = self.is_top_level(selector)
        hero = _hero
        if hero is None and not is_top and selector != '#hero-panel':
            hero = self.resolve_hero_panel(display_w, display_h)
        elif selector == '#hero-panel':
            is_top = True
        base_w = display_w if is_top or hero is None else hero[2]
        base_h = display_h if is_top or hero is None else hero[3]

        w = self._get_pct(selector, 'width', base_w)
        h = self._get_pct(selector, 'height', base_h)
        if w is None:
            w = 100.0
        if h is None:
            h = 100.0

        x = 0.0
        y = 0.0
        left = self._get_pct(selector, 'left', base_w)
        right = self._get_pct(selector, 'right', base_w)
        top = self._get_pct(selector, 'top', base_h)
        bottom = self._get_pct(selector, 'bottom', base_h)

        if left is not None:
            x = left
        elif right is not None:
            x = base_w - right - w

        if top is not None:
            y = top
        elif bottom is not None:
            y = base_h - bottom - h

        transform = self.doc.get_prop(selector, 'transform') or ""
        if 'translateX(-50%)' in transform or 'translatex(-50%)' in transform:
            x -= w * 0.5
        if 'translateY(-50%)' in transform or 'translatey(-50%)' in transform:
            y -= h * 0.5

        if not is_top and hero is not None:
            x += hero[0]
            y += hero[1]

        return (x, y, w, h)

    def resolve_hero_panel(self, display_w=VIRTUAL_WIDTH, display_h=VIRTUAL_HEIGHT):
        return self.resolve('#hero-panel', display_w, display_h)

    @staticmethod
    def is_top_level(selector):
        for name, sel, top in EDITABLE_COMPONENTS:
            if sel == selector:
                return top
        return True


class Component:
    def __init__(self, name, selector, is_top, z_index=0):
        self.name = name
        self.selector = selector
        self.is_top = is_top
        self.z_index = z_index
        self.dragging = False
        self.resizing = False
        self.resize_handle = None
        self.resize_start_rect = None
        self.resize_start_mouse = None
        self.offset = (0.0, 0.0)
        self.bind_to_player = False

    @property
    def rect(self):
        return pygame.Rect(int(round(self.fx)), int(round(self.fy)),
                           int(round(self.fw)), int(round(self.fh)))

    def screen_rect(self):
        """Retorna o rect final na tela, considerando bind_to_player e zoom."""
        if self.bind_to_player:
            zoom = PLAYER_ZOOM_SCALE
            return pygame.Rect(
                int(round(PLAYER_POS[0] + self.fx * zoom)),
                int(round(PLAYER_POS[1] + self.fy * zoom)),
                int(round(self.fw * zoom)),
                int(round(self.fh * zoom))
            )
        return self.rect

    def update_from_css(self, resolver):
        doc = resolver.doc
        if self.bind_to_player:
            left = parse_length(doc.get_prop(self.selector, 'left'), VIRTUAL_WIDTH)
            top = parse_length(doc.get_prop(self.selector, 'top'), VIRTUAL_HEIGHT)
            width = parse_length(doc.get_prop(self.selector, 'width'), VIRTUAL_WIDTH)
            height = parse_length(doc.get_prop(self.selector, 'height'), VIRTUAL_HEIGHT)
            self.fx = float(left if left is not None else 0.0)
            self.fy = float(top if top is not None else 0.0)
            self.fw = float(width if width is not None else 100.0)
            self.fh = float(height if height is not None else 100.0)
        else:
            x, y, w, h = resolver.resolve(self.selector)
            self.fx = float(x)
            self.fy = float(y)
            self.fw = float(w)
            self.fh = float(h)

    def set_position(self, abs_x, abs_y, resolver, doc):
        if self.bind_to_player:
            # abs_x/abs_y são a posição visual na tela; convertemos para offset
            # não-zoomado, igual ao CSS da engine.
            zoom = PLAYER_ZOOM_SCALE
            self.fx = (abs_x - PLAYER_POS[0]) / zoom
            self.fy = (abs_y - PLAYER_POS[1]) / zoom
            doc.set_prop(self.selector, 'left', f"{self.fx:.1f}px")
            doc.set_prop(self.selector, 'top', f"{self.fy:.1f}px")
            doc.set_prop(self.selector, 'right', None)
            doc.set_prop(self.selector, 'bottom', None)
            # width/height permanecem em pixels absolutos (não-zoomados)
            doc.set_prop(self.selector, 'width', f"{self.fw:.1f}px")
            doc.set_prop(self.selector, 'height', f"{self.fh:.1f}px")
            return

        hero = resolver.resolve_hero_panel()
        if self.is_top:
            left_ratio = abs_x / VIRTUAL_WIDTH
            top_ratio = abs_y / VIRTUAL_HEIGHT
            width_ratio = self.fw / VIRTUAL_WIDTH
            height_ratio = self.fh / VIRTUAL_HEIGHT
            doc.set_prop(self.selector, 'left', to_percent_str(left_ratio))
            doc.set_prop(self.selector, 'top', to_percent_str(top_ratio))
            doc.set_prop(self.selector, 'width', to_percent_str(width_ratio))
            doc.set_prop(self.selector, 'height', to_percent_str(height_ratio))
            doc.set_prop(self.selector, 'right', None)
            doc.set_prop(self.selector, 'bottom', None)
        else:
            rel_x = abs_x - hero[0]
            rel_y = abs_y - hero[1]
            left_ratio = rel_x / hero[2]
            top_ratio = rel_y / hero[3]
            width_ratio = self.fw / hero[2]
            height_ratio = self.fh / hero[3]
            doc.set_prop(self.selector, 'left', to_percent_str(left_ratio))
            doc.set_prop(self.selector, 'top', to_percent_str(top_ratio))
            doc.set_prop(self.selector, 'width', to_percent_str(width_ratio))
            doc.set_prop(self.selector, 'height', to_percent_str(height_ratio))
            doc.set_prop(self.selector, 'right', None)
            doc.set_prop(self.selector, 'bottom', None)
        # Limpa transform para que left/top sejam interpretados literalmente após mover
        doc.set_prop(self.selector, 'transform', None)
        self.update_from_css(resolver)

    def set_size(self, w, h, resolver, doc):
        self.fw = float(w)
        self.fh = float(h)
        if self.bind_to_player:
            doc.set_prop(self.selector, 'width', f"{self.fw:.1f}px")
            doc.set_prop(self.selector, 'height', f"{self.fh:.1f}px")
        # Usa a posição visual final para que set_position converta corretamente.
        rect = self.screen_rect()
        self.set_position(rect.x, rect.y, resolver, doc)


class CSSRenderer:
    """Renderizador CSS que reproduz o desenho da HUD da engine (HudRenderer)."""

    def __init__(self, doc, screen_scale=1.0):
        self.doc = doc
        self.scale = screen_scale
        self.font = None
        self.big_font = None
        self.small_font = None
        self.images = {}
        self.hero = HeroPreview()

    def set_fonts(self, font, big_font, small_font):
        self.font = font
        self.big_font = big_font
        self.small_font = small_font

    def load_images(self):
        paths = {
            # Imagens opcionais do preview. Se nao existirem, o Caldera desenha
            # os slots vazios; o jogo pode colocar as suas nesses caminhos.
            'portrait': os.path.join(ASSETS_DIR, 'hud', 'portrait.png'),
            'skill0': os.path.join(ASSETS_DIR, 'hud', 'skill_1.png'),
            'skill1': os.path.join(ASSETS_DIR, 'hud', 'skill_2.png'),
            'skill2': os.path.join(ASSETS_DIR, 'hud', 'skill_3.png'),
            'skill3': os.path.join(ASSETS_DIR, 'hud', 'skill_4.png'),
        }
        for key, path in paths.items():
            if os.path.exists(path):
                try:
                    self.images[key] = pygame.image.load(path).convert_alpha()
                except Exception:
                    pass
        # Sprite do heroi para o preview (PNG; o formato de runtime e' ERUPTSPR)
        self.hero.load(os.path.join(ASSETS_DIR, 'sprites', 'default'))

    # ------------------------------------------------------------------
    # Utilidades geométricas / cores
    # ------------------------------------------------------------------
    def _color(self, selector, prop, fallback):
        val = self.doc.get_prop(selector, prop)
        if val is None:
            return fallback
        c = hex_to_rgba(val)
        return c if c else fallback

    def bg(self, selector, fallback=(0, 0, 0, 0)):
        return self._color(selector, 'background-color', fallback)

    def bc(self, selector, fallback=(200, 200, 200, 255)):
        return self._color(selector, 'border-color', fallback)

    def tc(self, selector, fallback=(255, 255, 255, 255)):
        return self._color(selector, 'color', fallback)

    def bw(self, selector, fallback=0.0):
        val = self.doc.get_prop(selector, 'border-width')
        if val is None:
            return fallback
        try:
            return float(val.replace('px', '').strip())
        except ValueError:
            return fallback

    def _to_screen(self, x, y, w=None, h=None):
        if w is None:
            return (int(x * self.scale), int(y * self.scale))
        return pygame.Rect(int(x * self.scale), int(y * self.scale),
                           max(1, int(w * self.scale)), max(1, int(h * self.scale)))

    def _to_screen_pts(self, pts):
        return [(int(p[0] * self.scale), int(p[1] * self.scale)) for p in pts]

    def _shade(self, c, f):
        return shade_color(c, f)

    def _alpha(self, c, a):
        return alpha_color(c, a)

    def _lerp(self, a, b, t):
        return lerp_color(a, b, t)

    # ------------------------------------------------------------------
    # Clip-path
    # ------------------------------------------------------------------
    def _parse_clip_coord(self, token, base_w, base_h, axis):
        t = token.strip()
        if t == '50%':
            return (base_w if axis == 'x' else base_h) * 0.5
        if t.startswith('calc(') and t.endswith(')'):
            expr = t[5:-1]
            # suporta "100% + Npx" ou "100% - Npx"
            for op in ('+-', '-', '+'):
                if op in expr:
                    idx = expr.find(op)
                    left = expr[:idx].strip()
                    right = expr[idx + len(op):].strip()
                    base = parse_length(left, base_w if axis == 'x' else base_h) if left == '100%' else 0.0
                    offset = parse_length(right, 1.0)
                    return base + offset if '+' in op else base - offset
        return parse_length(t, base_w if axis == 'x' else base_h)

    def _parse_polygon(self, clip_path, rect):
        if not (clip_path.startswith('polygon(') and clip_path.endswith(')')):
            return None
        inner = clip_path[8:-1]
        pairs = []
        cur = ''
        depth = 0
        for ch in inner:
            if ch == '(':
                depth += 1
                cur += ch
            elif ch == ')':
                depth -= 1
                cur += ch
            elif ch == ',' and depth == 0:
                pairs.append(cur.strip())
                cur = ''
            else:
                cur += ch
        if cur.strip():
            pairs.append(cur.strip())
        pts = []
        for pair in pairs:
            raw = pair.split()
            # junta tokens que pertencem a uma expressão calc(...)
            coords = []
            cur = ''
            for tok in raw:
                if cur:
                    cur += ' ' + tok
                    if tok.endswith(')'):
                        coords.append(cur)
                        cur = ''
                elif tok.startswith('calc('):
                    cur = tok
                    if tok.endswith(')'):
                        coords.append(cur)
                        cur = ''
                else:
                    coords.append(tok)
            if cur:
                coords.append(cur)
            if len(coords) >= 2:
                x = self._parse_clip_coord(coords[0], rect[2], rect[3], 'x')
                y = self._parse_clip_coord(coords[1], rect[2], rect[3], 'y')
                if x is not None and y is not None:
                    pts.append((x + rect[0], y + rect[1]))
        return pts if len(pts) >= 3 else None

    # ------------------------------------------------------------------
    # Primitivas de desenho
    # ------------------------------------------------------------------
    def _draw_shadow(self, surf, pts, color, expand, steps):
        for s in range(1, steps + 1):
            t = s / steps
            e = expand * t
            a = int(color[3] * (1.0 - t) * 0.5)
            if a <= 2:
                continue
            shadow = [(p[0] + e, p[1] + e) for p in pts]
            for i in range(len(shadow)):
                pygame.draw.line(surf, color[:3] + (a,), shadow[i], shadow[(i + 1) % len(shadow)], 1)

    def _draw_forged_border(self, surf, pts, color, bw):
        if bw <= 0:
            return
        dark = self._shade(color, 0.5)
        light = self._shade(color, 1.4)
        for i in range(len(pts)):
            pygame.draw.line(surf, dark, pts[i], pts[(i + 1) % len(pts)], max(1, int(bw + 1)))
        for i in range(len(pts)):
            pygame.draw.line(surf, light, pts[i], pts[(i + 1) % len(pts)], max(1, int(bw * 0.6)))
        for i in range(len(pts)):
            pygame.draw.line(surf, color, pts[i], pts[(i + 1) % len(pts)], max(1, int(bw * 0.4)))

    def _draw_metal_texture(self, surf, rect, base, line_gap=4):
        highlight = self._alpha(self._shade(base, 1.6), 20)
        y = rect[1] + 2
        while y < rect[1] + rect[3] - 2:
            pygame.draw.line(surf, highlight, (rect[0] + 2, y), (rect[0] + rect[2] - 2, y), 1)
            y += line_gap

    def _rounded_radius(self, selector):
        val = self.doc.get_prop(selector, 'border-radius')
        if val is None:
            return 0.0
        try:
            return float(val.replace('px', '').strip())
        except ValueError:
            return 0.0

    def _draw_clipped(self, surf, selector, rect, bg, bc, bw):
        if rect[2] <= 0 or rect[3] <= 0:
            return
        clip = self.doc.get_prop(selector, 'clip-path') or ""
        pts = self._parse_polygon(clip, rect)
        srect = self._to_screen(rect[0], rect[1], rect[2], rect[3])
        if pts is None:
            rr = int(self._rounded_radius(selector) * self.scale)
            shadow_r = srect.move(int(4 * self.scale), int(4 * self.scale))
            pygame.draw.rect(surf, (0, 0, 0, 120), shadow_r, border_radius=rr)
            if bg[3] > 0:
                pygame.draw.rect(surf, bg, srect, border_radius=rr)
            self._draw_metal_texture(surf, (rect[0], rect[1], rect[2], rect[3]), bg)
            if bw > 0 and bc[3] > 0:
                pygame.draw.rect(surf, self._shade(bc, 0.5), srect, max(1, int((bw + 1) * self.scale)), border_radius=rr)
                pygame.draw.rect(surf, self._shade(bc, 1.4), srect, max(1, int(bw * 0.5 * self.scale)), border_radius=rr)
                pygame.draw.rect(surf, bc, srect, max(1, int(bw * 0.5 * self.scale)), border_radius=rr)
            return
        spts = self._to_screen_pts(pts)
        self._draw_shadow(surf, spts, (0, 0, 0, 160), 6.0, 4)
        if bg[3] > 0:
            pygame.draw.polygon(surf, bg, spts)
        self._draw_forged_border(surf, spts, bc, bw)

    def _draw_style_box(self, surf, selector, rect):
        bg = self.bg(selector, (0, 0, 0, 0))
        bw = self.bw(selector, 0.0)
        bc = self.bc(selector, (0, 0, 0, 0))
        self._draw_clipped(surf, selector, rect, bg, bc, bw)

    def _draw_text_stroke(self, surf, pos, color, text, font=None):
        f = font or self.font
        if f is None:
            return
        stroke = (0, 0, 0, 220)
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            t = f.render(text, True, stroke)
            surf.blit(t, (pos[0] + dx, pos[1] + dy))
        t = f.render(text, True, color)
        surf.blit(t, pos)

    def _draw_text_center(self, surf, rect, color, text, font=None):
        f = font or self.font
        if f is None:
            return
        t = f.render(text, True, color)
        r = t.get_rect(center=(int((rect[0] + rect[2] * 0.5) * self.scale), int((rect[1] + rect[3] * 0.5) * self.scale)))
        surf.blit(t, r)

    def _hex_points(self, rect):
        cx = rect[0] + rect[2] * 0.5
        cy = rect[1] + rect[3] * 0.5
        rx = rect[2] * 0.5
        ry = rect[3] * 0.5
        return [
            (cx, cy - ry),
            (cx + rx, cy - ry * 0.5),
            (cx + rx, cy + ry * 0.5),
            (cx, cy + ry),
            (cx - rx, cy + ry * 0.5),
            (cx - rx, cy - ry * 0.5),
        ]

    def _draw_hex(self, surf, rect, bg, bc, bw):
        pts = self._hex_points(rect)
        spts = self._to_screen_pts(pts)
        self._draw_shadow(surf, spts, (0, 0, 0, 180), 8.0, 4)
        if bg[3] > 0:
            pygame.draw.polygon(surf, bg, spts)
        self._draw_forged_border(surf, spts, bc, bw)

    # ------------------------------------------------------------------
    # Elementos específicos
    # ------------------------------------------------------------------
    def draw_boss_hp(self, surf, rect):
        selector = '#boss-hp-bar'
        inset = 24.0
        pts = [
            (rect[0], rect[1]),
            (rect[0] + rect[2], rect[1]),
            (rect[0] + rect[2] - inset, rect[1] + rect[3]),
            (rect[0] + inset, rect[1] + rect[3]),
        ]
        spts = self._to_screen_pts(pts)
        boss_bg = self.bg(selector, (26, 29, 36, 216))
        boss_bc = self.bc(selector, (139, 90, 43, 255))
        self._draw_shadow(surf, spts, (0, 0, 0, 180), 10.0, 5)
        pygame.draw.polygon(surf, boss_bg, spts)
        self._draw_forged_border(surf, spts, boss_bc, 3.0)

        hp_ratio = 0.72
        bar_h = 14.0
        bar_y = rect[1] + rect[3] - bar_h - 8.0
        min_x = rect[0] + inset + 8.0
        max_x = rect[0] + rect[2] - inset - 8.0
        fill_x = min_x + (max_x - min_x) * hp_ratio
        s_min = self._to_screen(min_x, bar_y)
        s_max = self._to_screen(max_x, bar_y + bar_h)
        pygame.draw.rect(surf, (10, 10, 12, 255), pygame.Rect(s_min[0], s_min[1], s_max[0] - s_min[0], s_max[1] - s_min[1]), border_radius=2)
        if hp_ratio > 0:
            c0 = (122, 11, 0, 255)
            c1 = (255, 77, 0, 255)
            steps = 8
            step_w = (fill_x - min_x) / steps
            for i in range(steps):
                t0 = i / steps
                t1 = (i + 1) / steps
                col = self._lerp(self._lerp(c0, c1, t0), self._lerp(c0, c1, t1), 0.5)
                q0 = self._to_screen(min_x + i * step_w, bar_y + 1)
                q1 = self._to_screen(min_x + (i + 1) * step_w, bar_y + bar_h - 1)
                pygame.draw.rect(surf, col, pygame.Rect(q0[0], q0[1], max(1, q1[0] - q0[0]), q1[1] - q0[1]))
            for i in range(1, 4):
                dx = min_x + (max_x - min_x) * (i / 4.0)
                sdx = int(dx * self.scale)
                pygame.draw.line(surf, (0, 0, 0, 120), (sdx, int((bar_y + 1) * self.scale)), (sdx, int((bar_y + bar_h - 1) * self.scale)), 1)

        text_color = self.tc(selector, (255, 100, 30, 255))
        self._draw_text_stroke(surf, self._to_screen(rect[0] + rect[2] * 0.5 - 80, rect[1] + 7), text_color, "BOSS")
        self._draw_text_stroke(surf, self._to_screen(rect[0] + rect[2] - 160, rect[1] + rect[3] - 23), (240, 230, 210, 255), "72 / 100")

    def draw_hero_panel(self, surf, rect):
        self._draw_style_box(surf, '#hero-panel', rect)

    def draw_portrait(self, surf, rect):
        selector = '#hero-portrait'
        bg = self.bg(selector, (26, 29, 36, 255))
        bc = self.bc(selector, (205, 127, 50, 255))
        bw = self.bw(selector, 3.0)
        self._draw_hex(surf, rect, bg, bc, bw)
        cx = rect[0] + rect[2] * 0.5
        cy = rect[1] + rect[3] * 0.5
        img = self.images.get('portrait')
        if img:
            size = int(min(rect[2], rect[3]) * self.scale)
            scaled = pygame.transform.smoothscale(img, (size, size))
            pos = self._to_screen(cx - rect[2] * 0.5, cy - rect[3] * 0.5)
            surf.blit(scaled, pos)
        else:
            self._draw_text_center(surf, (cx - rect[2] * 0.5, cy - rect[3] * 0.5, rect[2], rect[3]), (250, 204, 21, 255), "H", self.big_font)
        self._draw_forged_border(surf, self._to_screen_pts(self._hex_points(rect)), bc, bw)
        self._draw_text_stroke(surf, self._to_screen(cx - 50, rect[1] + rect[3] + 8), (148, 163, 184, 255), "Hero")

    def draw_level(self, surf, rect):
        selector = '#hero-level'
        self._draw_style_box(surf, selector, rect)
        self._draw_text_center(surf, rect, self.tc(selector, (0, 0, 0, 255)), "Lv. 42")

    def draw_attr_matrix(self, surf, rect):
        selector = '#attr-matrix'
        self._draw_style_box(surf, selector, rect)
        pairs = ["STR", "VIG", "DEX", "WIS", "CON", "AGI"]
        cols = 2
        rows = 3
        cell_w = rect[2] / cols
        cell_h = rect[3] / rows
        content_w = cell_w * 0.78
        values = [12, 8, 10, 18, 14, 6]
        for i, label in enumerate(pairs):
            col = i % cols
            row = i // cols
            cell_x = rect[0] + col * cell_w + (cell_w - content_w) * 0.5
            cell_y = rect[1] + row * cell_h
            name_c = self.tc('#attr-matrix > .attr-row > .attr-name', (148, 163, 184, 255))
            val_c = self.tc('#attr-matrix > .attr-row > .attr-value', (255, 255, 255, 255))
            self._draw_text_stroke(surf, self._to_screen(cell_x, cell_y + 4), name_c, label)
            self._draw_text_stroke(surf, self._to_screen(cell_x + content_w - 24, cell_y + 4), val_c, str(values[i]))

    def draw_bar(self, surf, rect, ratio, color_low, color_high, selector, value_text):
        if rect[2] <= 0 or rect[3] <= 0:
            return
        ratio = max(0.0, min(1.0, ratio))
        self._draw_style_box(surf, selector, rect)
        pad = 3.0
        fill_w = rect[2] * ratio
        if fill_w > pad * 2:
            p0 = (rect[0] + pad, rect[1] + pad)
            p1 = (rect[0] + fill_w - pad, rect[1] + rect[3] - pad)
            steps = 8
            step_w = (p1[0] - p0[0]) / steps
            for i in range(steps):
                t0 = i / steps
                t1 = (i + 1) / steps
                col = self._lerp(self._lerp(color_low, color_high, t0), self._lerp(color_low, color_high, t1), 0.5)
                q0 = self._to_screen(p0[0] + i * step_w, p0[1])
                q1 = self._to_screen(p0[0] + (i + 1) * step_w, p1[1])
                pygame.draw.rect(surf, col, pygame.Rect(q0[0], q0[1], max(1, q1[0] - q0[0]), q1[1] - q0[1]))
            sheen_y = int((p0[1] + 1) * self.scale)
            pygame.draw.line(surf, (255, 255, 255, 60), (int(p0[0] * self.scale), sheen_y), (int(p1[0] * self.scale), sheen_y), 1)
        bw = self.bw(selector, 1.0)
        if bw > 0:
            srect = self._to_screen(rect[0], rect[1], rect[2], rect[3])
            pygame.draw.rect(surf, self._shade((71, 85, 105, 255), 0.5), srect, max(1, int(bw * self.scale)))
            pygame.draw.rect(surf, self._shade((226, 232, 240, 255), 1.3), srect.move(int(bw * self.scale), int(bw * self.scale)), max(1, int(bw * self.scale)))
        self._draw_text_center(surf, rect, (255, 255, 255, 255), value_text)

    def draw_hp_bar(self, surf, rect):
        self.draw_bar(surf, rect, 0.85, (255, 26, 26, 255), (255, 107, 107, 255), '#hero-hp-bar', "850 / 1000")

    def draw_sp_bar(self, surf, rect):
        self.draw_bar(surf, rect, 0.60, (37, 99, 235, 255), (96, 165, 250, 255), '#hero-sp-bar', "300 / 500")

    def draw_equipment(self, surf, rect):
        selector = '#equip-panel'
        self._draw_style_box(surf, selector, rect)
        labels = ["Helm", "Armor", "Boots", "Wep", "Acc1", "Acc2"]
        rarity_colors = [
            (156, 163, 175, 255),
            (34, 197, 94, 255),
            (59, 130, 246, 255),
            (168, 85, 247, 255),
            (245, 158, 11, 255),
            (34, 197, 94, 255),
        ]
        cols = 3
        rows = 2
        slot_w = 48.0
        slot_h = 48.0
        gap_x = (rect[2] - cols * slot_w) / (cols + 1)
        gap_y = (rect[3] - rows * slot_h) / (rows + 1)
        for i, label in enumerate(labels):
            col = i % cols
            row = i // cols
            sx = rect[0] + gap_x + col * (slot_w + gap_x)
            sy = rect[1] + gap_y + row * (slot_h + gap_y)
            slot_rect = (sx, sy, slot_w, slot_h)
            bg = self.bg('#equip-panel > .equip-slot', (15, 23, 42, 255))
            border = rarity_colors[i]
            bw = self.bw('#equip-panel > .equip-slot', 2.0)
            self._draw_hex(surf, slot_rect, bg, border, bw)
            pygame.draw.polygon(surf, (0, 0, 0, 60), self._to_screen_pts(self._hex_points(slot_rect)))
            text = label if i % 2 == 0 else "Empty"
            text_c = self.tc('#equip-panel > .equip-slot', (226, 232, 240, 255))
            if text == "Empty":
                text_c = self._alpha(text_c, 80)
            self._draw_text_center(surf, slot_rect, text_c, text)

    def draw_skill_frame(self, surf, min_p, max_p, border, bw, ready):
        s_min = self._to_screen(min_p[0], min_p[1])
        s_max = self._to_screen(max_p[0], max_p[1])
        rect = pygame.Rect(s_min[0], s_min[1], s_max[0] - s_min[0], s_max[1] - s_min[1])
        pygame.draw.rect(surf, (0, 0, 0, 100), rect.move(3, 3), border_radius=4)
        pygame.draw.rect(surf, (20, 23, 30, 230), rect, border_radius=4)
        pygame.draw.rect(surf, (0, 0, 0, 80), rect.inflate(-4, -4), 2, border_radius=3)
        pygame.draw.rect(surf, self._shade(border, 0.5), rect, max(1, int(bw + 1)), border_radius=4)
        pygame.draw.rect(surf, self._shade(border, 1.4), rect, max(1, int(bw * 0.5)), border_radius=4)
        pygame.draw.rect(surf, border, rect, max(1, int(bw * 0.5)), border_radius=4)
        if ready:
            for g in range(1, 4):
                a = 60 // g
                pygame.draw.rect(surf, (0, 168, 255, a), rect.inflate(g * 2, g * 2), 1, border_radius=4 + g)

    def draw_skills(self, surf, rect):
        selector = '#skill-slots'
        skill_names = ["Skill 1", "Skill 2", "Skill 3", "Skill 4"]
        keys = "1234"
        slot_size = 50.0
        gap = 10.0
        start_x = rect[0]
        y = rect[1]
        for i in range(4):
            min_p = (start_x + i * (slot_size + gap), y)
            max_p = (min_p[0] + slot_size, min_p[1] + slot_size)
            ready = i != 1
            border = self.bc('#skill-slots > .skill-slot.ready' if ready else '#skill-slots > .skill-slot',
                             (0, 168, 255, 255) if ready else (205, 127, 50, 255))
            self.draw_skill_frame(surf, min_p, max_p, border, 2.0, ready)
            img = self.images.get(f'skill{i}')
            if img:
                size = int(slot_size * self.scale)
                scaled = pygame.transform.smoothscale(img, (size, size))
                surf.blit(scaled, self._to_screen(min_p[0], min_p[1]))
            else:
                self._draw_text_center(surf, (min_p[0], min_p[1], slot_size, slot_size), (200, 200, 200, 255), skill_names[i])
            key = keys[i]
            ts = self.font.render(key, True, (240, 230, 210, 255)) if self.font else None
            if ts:
                kw, kh = ts.get_size()
                kr = pygame.Rect(self._to_screen(min_p[0] + 3, min_p[1] + 2), (kw + 5, kh + 3))
                pygame.draw.rect(surf, (20, 23, 30, 235), kr, border_radius=3)
                pygame.draw.rect(surf, (148, 163, 184, 255), kr, 1, border_radius=3)
                surf.blit(ts, (kr.x + 2, kr.y + 1))
            if not ready:
                cx = (min_p[0] + max_p[0]) * 0.5
                cy = (min_p[1] + max_p[1]) * 0.5
                r = slot_size * 0.5
                pts = [(cx, cy)]
                steps = 16
                ratio = 0.4
                for s in range(steps + 1):
                    ang = -math.pi * 0.5 + (1.0 - ratio) * 2.0 * math.pi * (s / steps)
                    pts.append((cx + math.cos(ang) * r, cy + math.sin(ang) * r))
                if len(pts) >= 3:
                    pygame.draw.polygon(surf, (10, 12, 18, 200), self._to_screen_pts(pts))
                self._draw_text_center(surf, (cx - 10, cy - 10, 20, 20), (255, 255, 255, 255), "2.4")
            else:
                self._draw_text_stroke(surf, self._to_screen(min_p[0] + 10, min_p[1] + 32), (150, 200, 255, 255), "25")

        min_p = (start_x + 4 * (slot_size + gap), y)
        max_p = (min_p[0] + slot_size, min_p[1] + slot_size)
        dash_border = self.bc('#skill-slots > .dash-slot', (107, 143, 94, 255))
        self.draw_skill_frame(surf, min_p, max_p, dash_border, 2.0, True)
        self._draw_text_stroke(surf, self._to_screen(min_p[0] + 2, min_p[1] + 2), (240, 230, 210, 255), "CTRL")
        self._draw_text_center(surf, (min_p[0], min_p[1] + 20, slot_size, slot_size - 20), (200, 200, 200, 255), "Dash")

    def draw_minimap(self, surf, rect):
        selector = '#minimap'
        # Fundo/borda do retângulo do minimapa (estilo CSS)
        self._draw_style_box(surf, selector, rect)

        # O mapa nativo Ã© sempre quadrado, encaixado no centro do retÃ¢ngulo CSS
        ui_size = min(rect[2], rect[3])
        map_x = rect[0] + (rect[2] - ui_size) * 0.5
        map_y = rect[1]
        s_map = self._to_screen(map_x, map_y, ui_size, ui_size)

        # Fundo do mapa
        pygame.draw.rect(surf, (20, 18, 16, 255), s_map)

        # Grid placeholder do terreno
        grid_color = (60, 60, 60, 80)
        for i in range(1, 8):
            x = int(map_x + i * (ui_size / 8.0))
            y = int(map_y + i * (ui_size / 8.0))
            pygame.draw.line(surf, grid_color, (x, s_map.y), (x, s_map.y + s_map.h), 1)
            pygame.draw.line(surf, grid_color, (s_map.x, y), (s_map.x + s_map.w, y), 1)

        # Marcador do jogador (cÃ­rculo vermelho/laranja com brilho)
        cx = int(map_x + ui_size * 0.5)
        cy = int(map_y + ui_size * 0.5)
        for g in range(3, 0, -1):
            a = 40 // g
            pygame.draw.circle(surf, (255, 60, 40, a), (cx, cy), 3 + g)
        pygame.draw.circle(surf, (0, 0, 0, 255), (cx, cy), 5)
        pygame.draw.circle(surf, (255, 60, 40, 255), (cx, cy), 3)

        # Marcador do boss (triÃ¢ngulo amarelo)
        bx = int(map_x + ui_size * 0.65)
        by = int(map_y + ui_size * 0.35)
        pts = [(bx, by - 6), (bx - 6, by + 3), (bx + 6, by + 3)]
        pygame.draw.polygon(surf, (255, 220, 0, 255), pts)
        pygame.draw.polygon(surf, (255, 60, 40, 255), pts, 2)

    def draw_minimap_info(self, surf, rect):
        map_name = "parana_field [125, 95]"
        time_text = datetime.now().strftime("%H:%M")
        map_label = self.font.render(map_name, True, (255, 220, 80, 255))
        time_label = self.font.render(time_text, True, (240, 230, 210, 255))
        map_w, map_h = map_label.get_size()
        time_w, time_h = time_label.get_size()
        box_w = max(map_w, time_w) + 12
        box_h = map_h + time_h + 12

        # Centraliza a caixa de texto dentro do retÃ¢ngulo do widget
        text_x = rect[0] + (rect[2] - box_w) * 0.5
        text_y = rect[1] + (rect[3] - box_h) * 0.5
        s_text = self._to_screen(text_x, text_y, box_w, box_h)
        pygame.draw.rect(surf, (16, 14, 12, 235), s_text, border_radius=3)
        pygame.draw.rect(surf, (139, 90, 43, 255), s_text, 1, border_radius=3)

        # Centraliza cada linha horizontalmente dentro da caixa
        self._draw_text_stroke(surf, (int(text_x + (box_w - map_w) * 0.5), int(text_y + 4)),
                               (255, 235, 150, 255), map_name)
        self._draw_text_stroke(surf, (int(text_x + (box_w - time_w) * 0.5), int(text_y + map_h + 6)),
                               (200, 230, 255, 255), time_text)

    # ------------------------------------------------------------------
    # Loading bar reference (engine-fixed, non-editable)
    # ------------------------------------------------------------------
    def draw_loading_bar_reference(self, surf):
        """Desenha a barra de loading in-game na posição EXATA em que a engine
        a renderiza (Engine::renderLoadingProgress): canto inferior direito,
        margin 40, 220x6, com o texto de % acima. Referência fixa (não
        editável) para posicionar widgets — ex.: o minimap — fora da zona
        dela."""
        margin, bar_w, bar_h = 40.0, 220.0, 6.0
        p_max = (VIRTUAL_WIDTH - margin, VIRTUAL_HEIGHT - margin)
        p_min = (p_max[0] - bar_w, p_max[1] - bar_h)
        # Keep-clear zone: barra + texto de porcentagem acima (~18px) + respiro
        zone = pygame.Rect(int(p_min[0]) - 5, int(p_min[1]) - 24,
                           int(bar_w) + 10, int(bar_h) + 30)
        # Zona a evitar (contorno tracejado vermelho)
        for x in range(zone.left, zone.right, 8):
            pygame.draw.line(surf, (255, 80, 60, 120), (x, zone.top), (min(x + 4, zone.right), zone.top))
            pygame.draw.line(surf, (255, 80, 60, 120), (x, zone.bottom - 1), (min(x + 4, zone.right), zone.bottom - 1))
        for y in range(zone.top, zone.bottom, 8):
            pygame.draw.line(surf, (255, 80, 60, 120), (zone.left, y), (zone.left, min(y + 4, zone.bottom)))
            pygame.draw.line(surf, (255, 80, 60, 120), (zone.right - 1, y), (zone.right - 1, min(y + 4, zone.bottom)))
        # Barra (track + preenchimento de exemplo)
        track = pygame.Rect(int(p_min[0]), int(p_min[1]), int(bar_w), int(bar_h))
        pygame.draw.rect(surf, (15, 15, 15, 220), track, border_radius=3)
        fill = pygame.Rect(track.x, track.y, int(bar_w * 0.6), int(bar_h))
        pygame.draw.rect(surf, (255, 60, 40, 255), fill, border_radius=3)
        # Texto de % acima da barra (como na engine)
        pct_font = pygame.font.Font(None, 20)
        pct = pct_font.render("60%", True, (200, 200, 200))
        surf.blit(pct, (int(p_max[0]) - pct.get_width(), int(p_min[1]) - pct.get_height() - 5))
        # Label da referência
        label = pct_font.render("Loading Bar (fixa)", True, (255, 120, 100))
        surf.blit(label, (zone.left, zone.top - label.get_height() - 2))

    # ------------------------------------------------------------------
    # Overhead / world-space player UI preview
    # ------------------------------------------------------------------
    def draw_player_placeholder(self, surf, center, base, sprite_h, dt=0.0):
        """Desenha o placeholder do personagem projetado como na engine.

        O sprite é centralizado em 'center' (centro visual do corpo), e o
        ponto BASE (âncora dos widgets bind-to-player) é marcado em 'base'.
        """
        cx, cy = center
        bx, by = base
        base_x, base_y = bx, by  # keep screen-space base for the ground reference line
        rendered = False

        # 1) Sprite do heroi (PNG)
        if self.hero.surface:
            sprite_surf = self.hero.surface
            orig_w, orig_h = sprite_surf.get_size()
            if orig_h > 0:
                scaled_h = int(sprite_h)
                scaled_w = int(orig_w * (scaled_h / orig_h))
                scaled = pygame.transform.smoothscale(sprite_surf, (scaled_w, scaled_h))
                rect = scaled.get_rect(center=(int(cx), int(cy)))
                surf.blit(scaled, rect)
                rendered = True

        # 2) Fallback to portrait PNG
        if not rendered:
            img = self.images.get('portrait')
            if img:
                orig_w, orig_h = img.get_size()
                scaled_h = int(sprite_h)
                scaled_w = int(orig_w * (scaled_h / orig_h))
                scaled = pygame.transform.smoothscale(img, (scaled_w, scaled_h))
                rect = scaled.get_rect(center=(int(cx), int(cy)))
                surf.blit(scaled, rect)
                rendered = True

        # 3) Geometric fallback
        if not rendered:
            body_h = sprite_h * 0.85
            body_w = sprite_h * 0.35
            head_r = sprite_h * 0.18
            pygame.draw.rect(surf, (80, 90, 110, 255),
                             (int(cx - body_w * 0.5), int(cy - body_h * 0.3),
                              int(body_w), int(body_h * 0.7)), border_radius=6)
            pygame.draw.circle(surf, (220, 200, 170, 255), (int(cx), int(cy - body_h * 0.45)), int(head_r))

        # Ground reference line at the player's base (chão).
        line_w = int(sprite_h * 2.5)
        line_y = int(base_y)
        pygame.draw.line(surf, (200, 200, 200, 200),
                         (int(base_x - line_w * 0.5), line_y),
                         (int(base_x + line_w * 0.5), line_y), 1)
        # Small vertical tick marking the base center.
        pygame.draw.line(surf, (200, 200, 200, 200),
                         (int(base_x), line_y - 4),
                         (int(base_x), line_y + 4), 1)

    def draw_overhead_bars(self, surf, rect, arc_rotation=None):
        """HP/SP sobre o personagem: duas barras retas empilhadas dentro do rect
        (HP em cima, SP embaixo). Mesmo desenho que a engine faz em HudRenderer."""
        hp_ratio = 0.85
        sp_ratio = 0.60
        x, y, w, h = int(rect[0]), int(rect[1]), max(4, int(rect[2])), max(4, int(rect[3]))
        gap = 1
        bar_h = max(2, (h - gap) // 2)

        def bar(top, ratio, fill):
            pygame.draw.rect(surf, (20, 22, 28, 230), (x, top, w, bar_h))
            fw = int((w - 2) * max(0.0, min(1.0, ratio)))
            if fw > 0:
                pygame.draw.rect(surf, fill, (x + 1, top + 1, fw, bar_h - 2))
            pygame.draw.rect(surf, (58, 65, 82, 255), (x, top, w, bar_h), 1)

        bar(y, hp_ratio, (200, 60, 60, 255))
        bar(y + bar_h + gap, sp_ratio, (70, 120, 220, 255))

    def draw_cast_bar_top(self, surf, rect, ratio=0.55):
        """Barra de conjuracao: barra reta simples no rect do CSS (fica logo abaixo
        das barras de HP/SP quando ambas sao bind-to-player). Rotulo pequeno embaixo."""
        x, y, w, h = int(rect[0]), int(rect[1]), max(4, int(rect[2])), max(3, int(rect[3]))
        bg = self._color('#cast-bar', 'background-color', (12, 16, 24, 240))
        bc = self._color('#cast-bar', 'border-color', (80, 110, 150, 255))
        pygame.draw.rect(surf, bg, (x, y, w, h), border_radius=2)
        fw = int((w - 2) * max(0.0, min(1.0, ratio)))
        if fw > 0:
            pygame.draw.rect(surf, (60, 190, 255, 255), (x + 1, y + 1, fw, h - 2))
        pygame.draw.rect(surf, bc, (x, y, w, h), 1, border_radius=2)
        if self.small_font:
            label = self.small_font.render("cast 0.4s / 0.8s", True, (230, 240, 255, 255))
            lw, lh = label.get_size()
            surf.blit(label, (int(x + (w - lw) * 0.5), y + h + 2))


    # ------------------------------------------------------------------
    # dispatcher
    # ------------------------------------------------------------------
    def draw_component(self, surf, selector, rect):
        if selector == '#boss-hp-bar':
            self.draw_boss_hp(surf, rect)
        elif selector == '#hero-panel':
            self.draw_hero_panel(surf, rect)
        elif selector == '#hero-portrait':
            self.draw_portrait(surf, rect)
        elif selector == '#hero-level':
            self.draw_level(surf, rect)
        elif selector == '#attr-matrix':
            self.draw_attr_matrix(surf, rect)
        elif selector == '#hero-hp-bar':
            self.draw_hp_bar(surf, rect)
        elif selector == '#hero-sp-bar':
            self.draw_sp_bar(surf, rect)
        elif selector == '#equip-panel':
            self.draw_equipment(surf, rect)
        elif selector == '#skill-slots':
            self.draw_skills(surf, rect)
        elif selector == '#minimap':
            self.draw_minimap(surf, rect)
        elif selector == '#minimap-info':
            self.draw_minimap_info(surf, rect)
        elif selector == '#cast-bar':
            self.draw_cast_bar_top(surf, rect)
        elif selector == '#overhead-hp-sp':
            self.draw_overhead_bars(surf, rect)
        else:
            self._draw_style_box(surf, selector, rect)


class HUDState:
    def __init__(self, doc):
        self.doc = doc
        self.resolver = CSSResolver(doc)
        self.components = []
        self.selector_to_component = {}
        self.selected_set = set()
        for name, selector, is_top in EDITABLE_COMPONENTS:
            z = 0
            z_val = doc.get_prop(selector, 'z-index')
            if z_val is not None:
                try:
                    z = int(z_val)
                except ValueError:
                    pass
            comp = Component(name, selector, is_top, z)
            bind_val = doc.get_prop(selector, '--bind-to-player')
            comp.bind_to_player = (bind_val is not None and bind_val.strip() == '1')
            comp.update_from_css(self.resolver)
            self.components.append(comp)
            self.selector_to_component[selector] = comp
        self.sort_by_z()

    def is_selected(self, selector):
        return selector in self.selected_set

    def select_only(self, selector):
        self.selected_set.clear()
        if selector:
            self.selected_set.add(selector)

    def toggle_select(self, selector):
        if selector in self.selected_set:
            self.selected_set.discard(selector)
        else:
            self.selected_set.add(selector)

    def clear_selection(self):
        self.selected_set.clear()

    def sort_by_z(self):
        self.components.sort(key=lambda c: c.z_index)

    def refresh_all(self):
        for comp in self.components:
            comp.update_from_css(self.resolver)

    def export_to_css(self):
        for comp in self.components:
            self.doc.set_prop(comp.selector, 'z-index', str(comp.z_index))
            self.doc.set_prop(comp.selector, 'position', 'absolute')
            self.doc.set_prop(comp.selector, '--bind-to-player', '1' if comp.bind_to_player else '0')
            # Use a posição visual final (já com zoom aplicado) para que a
            # conversão de volta para offset em set_position fique correta.
            rect = comp.screen_rect()
            comp.set_position(rect.x, rect.y, self.resolver, self.doc)
        self.doc.write()


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def snap(value, grid):
    if grid <= 0:
        return value
    return round(value / grid) * grid


class Button:
    def __init__(self, text, rect, callback=None):
        self.text = text
        self.rect = pygame.Rect(rect)
        self.callback = callback
        self.hovered = False

    def update(self, mouse_pos):
        self.hovered = self.rect.collidepoint(mouse_pos)

    def handle_click(self, pos):
        if self.rect.collidepoint(pos) and self.callback:
            self.callback()
            return True
        return False

    def draw(self, screen, font, fg=(240, 230, 210), bg=(139, 90, 43), bg_hover=(205, 127, 50)):
        color = bg_hover if self.hovered else bg
        pygame.draw.rect(screen, color, self.rect, border_radius=4)
        pygame.draw.rect(screen, fg, self.rect, 1, border_radius=4)
        text_surf = font.render(self.text, True, fg)
        text_rect = text_surf.get_rect(center=self.rect.center)
        screen.blit(text_surf, text_rect)


class ToggleButton(Button):
    def __init__(self, text, rect, initial=False, callback=None):
        super().__init__(text, rect, None)
        self.active = initial
        self.callback = callback

    def handle_click(self, pos):
        if self.rect.collidepoint(pos):
            self.active = not self.active
            if self.callback:
                self.callback(self.active)
            return True
        return False

    def draw(self, screen, font, fg=(240, 230, 210), bg=(60, 60, 64), bg_active=(107, 143, 94)):
        color = bg_active if self.active else bg
        pygame.draw.rect(screen, color, self.rect, border_radius=4)
        pygame.draw.rect(screen, fg, self.rect, 1, border_radius=4)
        text_surf = font.render(self.text, True, fg)
        text_rect = text_surf.get_rect(center=self.rect.center)
        screen.blit(text_surf, text_rect)


class LayerPanel:
    def __init__(self, rect, components, state):
        self.rect = pygame.Rect(rect)
        self.components = components
        self.state = state
        self.item_height = 28
        self.scroll = 0
        self.selected = None
        self.dragging_idx = None
        self.drag_y = 0
        self.drop_target = None

    def _list_start_y(self):
        return 36

    def visible_range(self):
        y = self._list_start_y()
        visible = (self.rect.h - y) // self.item_height
        return (self.scroll, min(len(self.components), self.scroll + visible))

    def draw(self, screen, font, header_font):
        surf = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        surf.fill((20, 22, 26, 245))
        pygame.draw.rect(surf, (139, 90, 43), surf.get_rect(), 2)
        header = header_font.render("Layers (drag to reorder)", True, (240, 230, 210))
        surf.blit(header, (10, 8))
        y = self._list_start_y()
        start, end = self.visible_range()

        # linha de drop
        if self.dragging_idx is not None and self.drop_target is not None:
            drop_y = y + (self.drop_target - self.scroll) * self.item_height
            if self.drop_target > self.dragging_idx:
                drop_y += self.item_height
            pygame.draw.line(surf, (255, 220, 80), (4, drop_y), (self.rect.w - 4, drop_y), 2)

        for idx in range(start, end):
            comp = self.components[idx]
            item_rect = pygame.Rect(4, y, self.rect.w - 8, self.item_height - 2)
            is_sel = comp.selector in self.state.selected_set
            if idx == self.dragging_idx:
                color = (107, 143, 94)
            elif is_sel:
                color = (80, 80, 90)
            else:
                color = (60, 60, 64)
            pygame.draw.rect(surf, color, item_rect, border_radius=3)
            pygame.draw.rect(surf, (139, 90, 43), item_rect, 1, border_radius=3)
            text = font.render(f"{comp.z_index}: {comp.name}", True, (240, 230, 210))
            surf.blit(text, (item_rect.x + 6, item_rect.y + 5))
            y += self.item_height
        screen.blit(surf, self.rect.topleft)

    def item_at(self, pos):
        x, y = pos[0] - self.rect.x, pos[1] - self.rect.y
        if not self.rect.collidepoint(pos):
            return None
        rel = y - self._list_start_y()
        if rel < 0:
            return None
        idx = self.scroll + rel // self.item_height
        if idx < len(self.components):
            return idx
        return None

    def start_drag(self, pos):
        idx = self.item_at(pos)
        if idx is not None:
            self.dragging_idx = idx
            self.selected = self.components[idx].selector
            self.update_drag(pos)
            return True
        return False

    def update_drag(self, pos):
        if self.dragging_idx is None:
            return
        x, y = pos[0] - self.rect.x, pos[1] - self.rect.y
        self.drag_y = y
        rel = y - self._list_start_y()
        target = self.scroll + max(0, rel // self.item_height)
        target = min(len(self.components), target)
        # ajusta para não colocar no mesmo lugar
        if target > self.dragging_idx:
            target -= 1
        self.drop_target = max(0, min(len(self.components) - 1, target))

    def end_drag(self):
        if self.dragging_idx is None or self.drop_target is None:
            self.dragging_idx = None
            self.drop_target = None
            return
        src = self.dragging_idx
        dst = self.drop_target
        if src != dst:
            comp = self.components.pop(src)
            self.components.insert(dst, comp)
            # renumera z-index conforme nova ordem
            for i, c in enumerate(self.components):
                c.z_index = i
        self.dragging_idx = None
        self.drop_target = None

    def move_selected(self, delta):
        # mantido para compatibilidade, mas não usado mais pelas setas
        if not self.state.selected_set:
            return
        sel = self.selected
        if sel is None:
            sel = next(iter(self.state.selected_set))
        for i, comp in enumerate(self.components):
            if comp.selector == sel:
                j = i + delta
                if 0 <= j < len(self.components):
                    self.components[i], self.components[j] = self.components[j], self.components[i]
                    self.components[i].z_index, self.components[j].z_index = self.components[j].z_index, self.components[i].z_index
                break


def main():
    pygame.init()

    screen_width = 1280
    screen_height = 720
    # CALDERA_WINDOW="LxA": tamanho inicial da janela (ex.: 1460x800 deixa o
    # canvas 1:1 com uma tela virtual de 1280x720).
    if os.environ.get('CALDERA_WINDOW'):
        try:
            _w, _h = os.environ['CALDERA_WINDOW'].lower().split('x')
            screen_width, screen_height = int(_w), int(_h)
        except ValueError:
            pass
    screen = pygame.display.set_mode((screen_width, screen_height), pygame.RESIZABLE)
    pygame.display.set_caption("Caldera HUD Designer - Eruption Engine")

    font = pygame.font.SysFont("Arial", 14, bold=True)
    header_font = pygame.font.SysFont("Arial", 16, bold=True)
    msg_font = pygame.font.SysFont("Arial", 18, bold=True)
    big_font = pygame.font.SysFont("Arial", 24, bold=True)
    small_font = pygame.font.SysFont("Arial", 12, bold=True)

    doc = CSSDocument(HUD_CSS_FILE)
    state = HUDState(doc)

    scale_x = 1.0
    scale_y = 1.0

    menu_open = False
    menu_height = 0
    target_menu_height = 0
    snap_enabled = True
    grid_size = 8
    show_grid = True
    show_layers = True
    lock_layer_order = True
    message = ""
    message_timer = 0
    overhead_arc_rotation = 0  # rotação do arco em graus (0, 90, 180, 270)
    debug_dist_timer = 0.0

    # Zoom da câmera: distance_ratio = orbitDistance / defaultOrbitDistance.
    # zoomScale = 1 / distance_ratio.  Valor 1.0 = distância default da engine
    # (158.5 u, que ela mostra como 'Zoom: 85%'). O preview abre igual ao jogo.
    player_zoom = 1.0
    PLAYER_CAMERA_ZOOM = player_zoom
    recalc_player_projection(player_zoom)

    # Repetição contínua de zoom/pitch ao segurar as teclas
    zoom_key_held = None
    zoom_key_timer = 0.0
    pitch_key_held = None
    pitch_key_timer = 0.0
    ZOOM_REPEAT_DELAY = 0.3
    ZOOM_REPEAT_INTERVAL = 0.05

    def set_zoom(value):
        nonlocal player_zoom
        # Limita para evitar que a câmera atravesse o sprite (inverte projeção).
        player_zoom = max(0.2, min(2.0, value))
        global PLAYER_CAMERA_ZOOM
        PLAYER_CAMERA_ZOOM = player_zoom
        recalc_player_projection(player_zoom)
        return player_zoom

    def adjust_zoom(delta):
        return set_zoom(player_zoom + delta)

    # Pitch da câmera (inclinação vertical).  Alterar o pitch muda a projeção
    # do BASE, então widgets bind-to-player acompanham o sprite.
    player_pitch = PLAYER_CAMERA_PITCH_DEG
    PITCH_MIN = 10.0
    PITCH_MAX = 89.0
    PITCH_STEP = 2.0

    def set_pitch(value):
        nonlocal player_pitch
        player_pitch = max(PITCH_MIN, min(PITCH_MAX, value))
        global PLAYER_CAMERA_PITCH_DEG
        PLAYER_CAMERA_PITCH_DEG = player_pitch
        recalc_player_projection(player_zoom)
        return player_pitch

    def adjust_pitch(delta):
        return set_pitch(player_pitch + delta)

    rot_val = doc.get_prop('#overhead-hp-sp', '--arc-rotation')
    if rot_val is not None:
        try:
            overhead_arc_rotation = int(float(rot_val.strip()))
        except ValueError:
            pass

    top_bar_height = 36
    menu_full_height = 64

    def menu_y():
        return top_bar_height + menu_height

    def layer_w():
        return 180 if show_layers else 0

    def available_area_rect():
        return pygame.Rect(0, menu_y(), screen_width - layer_w(), screen_height - menu_y())

    def design_area_rect():
        """Canvas com a MESMA escala em X e Y (proporcao da tela virtual), centrado
        na area disponivel. Antes escalava X e Y separadamente e esticava tudo
        quando a janela nao tinha a proporcao 16:9."""
        avail = available_area_rect()
        s = min(avail.w / VIRTUAL_WIDTH, avail.h / VIRTUAL_HEIGHT)
        w = int(VIRTUAL_WIDTH * s)
        h = int(VIRTUAL_HEIGHT * s)
        return pygame.Rect(avail.x + (avail.w - w) // 2, avail.y + (avail.h - h) // 2, w, h)

    def layer_panel_rect():
        lw = layer_w()
        return pygame.Rect(screen_width - lw, menu_y(), lw, screen_height - menu_y())

    layer_panel = LayerPanel(layer_panel_rect(), state.components, state)

    def to_design(rect):
        """Converte rect virtual para coordenadas relativas à área de design."""
        return pygame.Rect(
            int(rect.x * scale_x),
            int(rect.y * scale_y),
            max(1, int(rect.w * scale_x)),
            max(1, int(rect.h * scale_y)),
        )

    def to_screen(rect):
        """Converte rect virtual para coordenadas absolutas da tela."""
        design = design_area_rect()
        r = to_design(rect)
        r.move_ip(design.left, design.top)
        return r

    def to_virtual(x, y):
        """Converte coordenadas de tela para virtuais relativas à área de design."""
        design = design_area_rect()
        return (x - design.left) / scale_x, (y - design.top) / scale_y

    def export():
        state.export_to_css()
        # Sincroniza rotação do arco overhead
        state.doc.set_prop('#overhead-hp-sp', '--arc-rotation', str(overhead_arc_rotation))
        state.doc.write()

        nonlocal message, message_timer
        message = "Exportado para data/hud/default.css"
        message_timer = 180

    def toggle_menu():
        nonlocal menu_open, target_menu_height
        menu_open = not menu_open
        target_menu_height = menu_full_height if menu_open else 0

    def set_snap(value):
        nonlocal snap_enabled
        snap_enabled = value
        btn_snap.active = value
        btn_snap_menu.active = value

    def reset_defaults():
        defaults = {
            "#boss-hp-bar":  (620.0, 24.0, 680.0, 56.0),
            "#hero-panel":   (0.0, 912.0, 1920.0, 168.0),
            "#hero-portrait": (24.0, 828.0, 96.0, 96.0),
            "#hero-level":   (24.0, 790.0, 96.0, 18.0),
            "#attr-matrix":  (136.0, 884.0, 240.0, 32.0),
            "#hero-hp-bar":  (136.0, 854.0, 240.0, 22.0),
            "#hero-sp-bar":  (136.0, 824.0, 240.0, 22.0),
            "#equip-panel":  (392.0, 828.0, 200.0, 96.0),
            "#skill-slots":  (815.0, 892.0, 290.0, 52.0),
            "#minimap":      (1656.0, 816.0, 240.0, 240.0),
        }
        for comp in state.components:
            if comp.selector in defaults:
                x, y, w, h = defaults[comp.selector]
                comp.fw = w
                comp.fh = h
                comp.set_position(x, y, state.resolver, state.doc)
        state.sort_by_z()
        layer_panel.components = state.components

    renderer = CSSRenderer(doc, 1.0)
    renderer.set_fonts(font, big_font, small_font)
    renderer.load_images()

    def update_scale():
        nonlocal scale_x, scale_y
        avail = available_area_rect()
        scale_x = min(avail.w / VIRTUAL_WIDTH, avail.h / VIRTUAL_HEIGHT)
        scale_y = scale_x

    update_scale()

    def toggle_layers():
        nonlocal show_layers
        show_layers = not show_layers
        btn_layers.active = show_layers
        btn_layers_menu.active = show_layers

    def set_lock_layer_order(value):
        nonlocal lock_layer_order
        lock_layer_order = value
        btn_lock.active = value
        btn_lock_menu.active = value

    def toggle_bind_to_player(active):
        """Alterna o modo bind_to_player dos widgets selecionados, preservando posição visual."""
        targets = [c for c in state.components if c.selector in state.selected_set]
        if not targets:
            return
        for comp in targets:
            if active == comp.bind_to_player:
                continue
            # Captura a posição visual ANTES de mudar o modo (o significado de fx/fy muda)
            visual_x = comp.screen_rect().x
            visual_y = comp.screen_rect().y
            comp.bind_to_player = active
            if active:
                # HUD -> Player: offset = posicao_atual - PLAYER_POS
                comp.fx = visual_x - PLAYER_POS[0]
                comp.fy = visual_y - PLAYER_POS[1]
            else:
                # Player -> HUD: posicao = PLAYER_POS + offset
                comp.fx = visual_x
                comp.fy = visual_y
            # Atualiza CSS imediatamente para refletir o novo espaço
            comp.set_position(visual_x, visual_y, state.resolver, state.doc)

    def rotate_overhead_arc():
        nonlocal overhead_arc_rotation
        overhead_arc_rotation = (overhead_arc_rotation + 90) % 360
        state.doc.set_prop('#overhead-hp-sp', '--arc-rotation', str(overhead_arc_rotation))

    btn_export = Button("Export", (8, 6, 80, 24), export)
    btn_menu = Button("Menu ▼", (96, 6, 80, 24), toggle_menu)
    btn_layers = ToggleButton("Layers", (184, 6, 80, 24), show_layers, lambda v: toggle_layers())
    btn_lock = ToggleButton("Lock", (272, 6, 80, 24), lock_layer_order, set_lock_layer_order)
    btn_snap = ToggleButton("Snap", (screen_width - layer_w() - 8 - 90, 6, 80, 24), snap_enabled, set_snap)
    btn_grid = ToggleButton("Grid", (screen_width - layer_w() - 8 - 180, 6, 80, 24), True, lambda v: set_grid(v))

    btn_export_menu = Button("Export to default.css", (8, top_bar_height + 8, 180, 32), export)
    btn_reset = Button("Reset to defaults", (196, top_bar_height + 8, 140, 32), reset_defaults)
    btn_snap_menu = ToggleButton(f"Snap grid ({grid_size}px)", (344, top_bar_height + 8, 140, 32), snap_enabled, set_snap)
    btn_layers_menu = ToggleButton("Layers panel (L)", (492, top_bar_height + 8, 140, 32), show_layers, lambda v: toggle_layers())
    btn_lock_menu = ToggleButton("Lock layer order (K)", (640, top_bar_height + 8, 160, 32), lock_layer_order, set_lock_layer_order)

    buttons = [btn_export, btn_menu, btn_layers, btn_lock, btn_snap, btn_grid]
    menu_buttons = [btn_export_menu, btn_reset, btn_snap_menu, btn_layers_menu, btn_lock_menu]

    def _get_selected_bind_mode():
        targets = [c for c in state.components if c.selector in state.selected_set]
        if not targets:
            return None
        return all(c.bind_to_player for c in targets)

    def update_bind_button():
        mode = _get_selected_bind_mode()
        if mode is None:
            btn_bind_to_player.text = "Bind: -"
            btn_bind_to_player.active = False
        else:
            btn_bind_to_player.text = f"Bind: {'Player' if mode else 'HUD'}"
            btn_bind_to_player.active = mode

    btn_bind_to_player = ToggleButton("Bind: HUD", (screen_width - layer_w() - 8 - 380, 6, 90, 24),
                                      False, toggle_bind_to_player)
    buttons.append(btn_bind_to_player)


    def set_grid(value):
        nonlocal show_grid
        show_grid = value
        btn_grid.active = value

    def draw_guide_line(surf, p1, p2, color=(255, 60, 60, 255), dash=6):
        x1, y1 = int(p1[0]), int(p1[1])
        x2, y2 = int(p2[0]), int(p2[1])
        if x1 == x2:
            y_min, y_max = min(y1, y2), max(y1, y2)
            y = y_min
            while y < y_max:
                seg = min(dash, y_max - y)
                pygame.draw.line(surf, color, (x1, y), (x2, y + seg), 1)
                y += dash * 2
        else:
            x_min, x_max = min(x1, x2), max(x1, x2)
            x = x_min
            while x < x_max:
                seg = min(dash, x_max - x)
                pygame.draw.line(surf, color, (x, y1), (x + seg, y2), 1)
                x += dash * 2

    def draw_guide_label(surf, text, pos, color=(255, 220, 80, 255), bg=(0, 0, 0, 180)):
        ts = font.render(text, True, color)
        tr = ts.get_rect(center=(int(pos[0]), int(pos[1])))
        pygame.draw.rect(surf, bg, tr.inflate(6, 4))
        surf.blit(ts, tr)

    def draw_guides(surf):
        target = None
        for comp in state.components:
            if comp.dragging or comp.selector in state.selected_set:
                target = comp
                break
        if target is None:
            return
        design = design_area_rect()
        hero = state.resolver.resolve_hero_panel()
        # Para bind_to_player o espaço de coordenadas é a tela virtual
        base_w = VIRTUAL_WIDTH if (target.bind_to_player or target.is_top) else hero[2]
        base_h = VIRTUAL_HEIGHT if (target.bind_to_player or target.is_top) else hero[3]
        origin_x = 0.0 if (target.bind_to_player or target.is_top) else hero[0]
        origin_y = 0.0 if (target.bind_to_player or target.is_top) else hero[1]

        tr = target.screen_rect()
        x, y, w, h = tr.x, tr.y, tr.w, tr.h
        cx = x + w * 0.5
        cy = y + h * 0.5
        right = x + w
        bottom = y + h

        guide_color = (255, 60, 60, 255)
        hp_color = (107, 143, 94, 255)

        def sx(v): return int(v * scale_x + design.left)
        def sy(v): return int(v * scale_y + design.top)

        min_x = origin_x
        max_x = origin_x + base_w
        min_y = origin_y
        max_y = origin_y + base_h

        def nearest_left(edge):
            best = None
            for other in state.components:
                if other is target:
                    continue
                oright = other.screen_rect().right
                if oright <= edge:
                    if best is None or oright > best:
                        best = oright
            return min_x if best is None else best

        def nearest_right(edge):
            best = None
            for other in state.components:
                if other is target:
                    continue
                ox = other.screen_rect().x
                if ox >= edge:
                    if best is None or ox < best:
                        best = ox
            return max_x if best is None else best

        def nearest_top(edge):
            best = None
            for other in state.components:
                if other is target:
                    continue
                obottom = other.screen_rect().bottom
                if obottom <= edge:
                    if best is None or obottom > best:
                        best = obottom
            return min_y if best is None else best

        def nearest_bottom(edge):
            best = None
            for other in state.components:
                if other is target:
                    continue
                oy = other.screen_rect().y
                if oy >= edge:
                    if best is None or oy < best:
                        best = oy
            return max_y if best is None else best

        def draw_horizontal_guide(x1, x2, yy, color, label_pct):
            draw_guide_line(surf, (sx(x1), sy(yy)), (sx(x2), sy(yy)), color)
            mid = ((sx(x1) + sx(x2)) * 0.5, sy(yy))
            draw_guide_label(surf, f"{label_pct:.1f}%", mid, color=color[:3] + (255,))

        def draw_vertical_guide(xx, y1, y2, color, label_pct):
            draw_guide_line(surf, (sx(xx), sy(y1)), (sx(xx), sy(y2)), color)
            mid = (sx(xx), (sy(y1) + sy(y2)) * 0.5)
            draw_guide_label(surf, f"{label_pct:.1f}%", mid, color=color[:3] + (255,))

        nl = nearest_left(x)
        color = hp_color if nl == min_x else guide_color
        draw_vertical_guide(x, cy, cy, color, ((x - nl) / base_w) * 100.0)

        nr = nearest_right(right)
        color = hp_color if nr == max_x else guide_color
        draw_vertical_guide(right, cy, cy, color, ((nr - right) / base_w) * 100.0)

        nt = nearest_top(y)
        color = hp_color if nt == min_y else guide_color
        draw_horizontal_guide(cx, cx, y, color, ((y - nt) / base_h) * 100.0)

        nb = nearest_bottom(bottom)
        color = hp_color if nb == max_y else guide_color
        draw_horizontal_guide(cx, cx, bottom, color, ((nb - bottom) / base_h) * 100.0)

        threshold = 4.0
        for other in state.components:
            if other is target:
                continue
            or_ = other.screen_rect()
            ox, oy, ow, oh = or_.x, or_.y, or_.w, or_.h
            ocx = ox + ow * 0.5
            ocy = oy + oh * 0.5
            oright = ox + ow
            obottom = oy + oh

            aligned_x = None
            if abs(x - ox) < threshold:
                aligned_x = x
            elif abs(cx - ocx) < threshold:
                aligned_x = cx
            elif abs(right - oright) < threshold:
                aligned_x = right

            if aligned_x is not None:
                draw_guide_line(surf, (sx(aligned_x), sy(min(y, oy))),
                                (sx(aligned_x), sy(max(bottom, obottom))), guide_color)

            aligned_y = None
            if abs(y - oy) < threshold:
                aligned_y = y
            elif abs(cy - ocy) < threshold:
                aligned_y = cy
            elif abs(bottom - obottom) < threshold:
                aligned_y = bottom

            if aligned_y is not None:
                draw_guide_line(surf, (sx(min(x, ox)), sy(aligned_y)),
                                (sx(max(right, oright)), sy(aligned_y)), guide_color)

        # ------------------------------------------------------------------
        # Player distance guides: distance from player to nearest objects/edges
        # ------------------------------------------------------------------
        px, py = PLAYER_POS
        base_w = VIRTUAL_WIDTH
        base_h = VIRTUAL_HEIGHT

        def nearest_obj_left(edge):
            best = None
            for comp in state.components:
                cright = comp.screen_rect().right
                if cright <= edge:
                    if best is None or cright > best:
                        best = cright
            return best

        def nearest_obj_right(edge):
            best = None
            for comp in state.components:
                cx_ = comp.screen_rect().x
                if cx_ >= edge:
                    if best is None or cx_ < best:
                        best = cx_
            return best

        def nearest_obj_top(edge):
            best = None
            for comp in state.components:
                cbottom = comp.screen_rect().bottom
                if cbottom <= edge:
                    if best is None or cbottom > best:
                        best = cbottom
            return best

        def nearest_obj_bottom(edge):
            best = None
            for comp in state.components:
                cy_ = comp.screen_rect().y
                if cy_ >= edge:
                    if best is None or cy_ < best:
                        best = cy_
            return best

        # Left of player
        obj = nearest_obj_left(px)
        edge = 0.0
        if obj is not None:
            draw_guide_line(surf, (sx(obj), sy(py)), (sx(px), sy(py)), guide_color)
            draw_guide_label(surf, f"{((px - obj) / base_w) * 100.0:.1f}%",
                             ((sx(obj) + sx(px)) * 0.5, sy(py)), color=guide_color[:3] + (255,))
        draw_guide_line(surf, (sx(edge), sy(py)), (sx(px), sy(py)), hp_color)
        draw_guide_label(surf, f"{((px - edge) / base_w) * 100.0:.1f}%",
                         ((sx(edge) + sx(px)) * 0.5, sy(py)), color=hp_color[:3] + (255,))

        # Right of player
        obj = nearest_obj_right(px)
        edge = VIRTUAL_WIDTH
        if obj is not None:
            draw_guide_line(surf, (sx(px), sy(py)), (sx(obj), sy(py)), guide_color)
            draw_guide_label(surf, f"{((obj - px) / base_w) * 100.0:.1f}%",
                             ((sx(px) + sx(obj)) * 0.5, sy(py)), color=guide_color[:3] + (255,))
        draw_guide_line(surf, (sx(px), sy(py)), (sx(edge), sy(py)), hp_color)
        draw_guide_label(surf, f"{((edge - px) / base_w) * 100.0:.1f}%",
                         ((sx(px) + sx(edge)) * 0.5, sy(py)), color=hp_color[:3] + (255,))

        # Top of player
        obj = nearest_obj_top(py)
        edge = 0.0
        if obj is not None:
            draw_guide_line(surf, (sx(px), sy(obj)), (sx(px), sy(py)), guide_color)
            draw_guide_label(surf, f"{((py - obj) / base_h) * 100.0:.1f}%",
                             (sx(px), (sy(obj) + sy(py)) * 0.5), color=guide_color[:3] + (255,))
        draw_guide_line(surf, (sx(px), sy(edge)), (sx(px), sy(py)), hp_color)
        draw_guide_label(surf, f"{((py - edge) / base_h) * 100.0:.1f}%",
                         (sx(px), (sy(edge) + sy(py)) * 0.5), color=hp_color[:3] + (255,))

        # Bottom of player
        obj = nearest_obj_bottom(py)
        edge = VIRTUAL_HEIGHT
        if obj is not None:
            draw_guide_line(surf, (sx(px), sy(py)), (sx(px), sy(obj)), guide_color)
            draw_guide_label(surf, f"{((obj - py) / base_h) * 100.0:.1f}%",
                             (sx(px), (sy(py) + sy(obj)) * 0.5), color=guide_color[:3] + (255,))
        draw_guide_line(surf, (sx(px), sy(py)), (sx(px), sy(edge)), hp_color)
        draw_guide_label(surf, f"{((edge - py) / base_h) * 100.0:.1f}%",
                         (sx(px), (sy(py) + sy(edge)) * 0.5), color=hp_color[:3] + (255,))

    # ------------------------------------------------------------------
    # Handles de redimensionamento
    # ------------------------------------------------------------------
    HANDLE_SIZE = 8
    HANDLE_NAMES = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']

    def handle_positions(rect):
        """Retorna dict {nome: (x, y)} em coordenadas virtuais para os 8 handles."""
        x, y, w, h = rect
        return {
            'nw': (x, y),
            'n':  (x + w * 0.5, y),
            'ne': (x + w, y),
            'e':  (x + w, y + h * 0.5),
            'se': (x + w, y + h),
            's':  (x + w * 0.5, y + h),
            'sw': (x, y + h),
            'w':  (x, y + h * 0.5),
        }

    def handle_at(mouse_pos, comp):
        if comp is None:
            return None
        hs = HANDLE_SIZE / scale_x
        r = comp.screen_rect()
        pos = handle_positions((r.x, r.y, r.w, r.h))
        mx, my = to_virtual(mouse_pos[0], mouse_pos[1])
        for name, (hx, hy) in pos.items():
            if abs(mx - hx) <= hs and abs(my - hy) <= hs:
                return name
        return None

    def draw_handles(surf, comp):
        if comp is None:
            return
        r = comp.screen_rect()
        pos = handle_positions((r.x, r.y, r.w, r.h))
        hs_screen = max(4, int(HANDLE_SIZE * 0.5))
        for name, (hx, hy) in pos.items():
            sr = to_screen(pygame.Rect(hx, hy, 0, 0))
            sx, sy = sr.x, sr.y
            rect = pygame.Rect(sx - hs_screen, sy - hs_screen, hs_screen * 2, hs_screen * 2)
            pygame.draw.rect(surf, (255, 220, 80), rect)
            pygame.draw.rect(surf, (0, 0, 0), rect, 1)

    def apply_resize(comp, handle, mx, my):
        """Calcula novo rect baseado no handle arrastado."""
        sx, sy, sw, sh = comp.resize_start_rect
        smx, smy = comp.resize_start_mouse
        dx = mx - smx
        dy = my - smy

        # snap se habilitado
        if snap_enabled:
            dx = snap(dx, grid_size)
            dy = snap(dy, grid_size)

        nx, ny, nw, nh = sx, sy, sw, sh

        if 'e' in handle:
            nw = sw + dx
        if 'w' in handle:
            nx = sx + dx
            nw = sw - dx
        if 's' in handle:
            nh = sh + dy
        if 'n' in handle:
            ny = sy + dy
            nh = sh - dy

        # tamanho mínimo
        min_size = 8.0
        if nw < min_size:
            if 'w' in handle:
                nx = sx + sw - min_size
            nw = min_size
        if nh < min_size:
            if 'n' in handle:
                ny = sy + sh - min_size
            nh = min_size

        # clamp na posição visual
        if comp.is_top:
            nx = max(0.0, min(VIRTUAL_WIDTH - nw, nx))
            ny = max(0.0, min(VIRTUAL_HEIGHT - nh, ny))
        else:
            hero = state.resolver.resolve_hero_panel()
            nx = max(hero[0] - VIRTUAL_WIDTH, min(hero[0] + hero[2] + VIRTUAL_WIDTH - nw, nx))
            ny = max(hero[1] - VIRTUAL_HEIGHT, min(hero[1] + hero[3] + VIRTUAL_HEIGHT - nh, ny))

        comp.set_size(nw, nh, state.resolver, state.doc)
        comp.set_position(nx, ny, state.resolver, state.doc)

    def nudge_selected(dx, dy, resize=False):
        targets = [c for c in state.components if c.selector in state.selected_set]
        if not targets:
            return
        for target in targets:
            if resize:
                if len(targets) > 1:
                    continue  # não redimensiona múltiplos via teclado
                if target.fw + dx < 8.0:
                    dx = 0
                if target.fh + dy < 8.0:
                    dy = 0
                nw = max(8.0, target.fw + dx)
                nh = max(8.0, target.fh + dy)
                target.set_size(nw, nh, state.resolver, state.doc)
                continue

            # Usa posição visual atual e aplica o nudge; set_position converte para o espaço correto
            r = target.screen_rect()
            nx = r.x + dx
            ny = r.y + dy
            if target.bind_to_player:
                # Clamp do offset em ±500px (limite arbitrário de segurança)
                nx = max(PLAYER_POS[0] - 500.0, min(PLAYER_POS[0] + 500.0, nx))
                ny = max(PLAYER_POS[1] - 500.0, min(PLAYER_POS[1] + 500.0, ny))
            elif target.is_top:
                nx = max(0.0, min(VIRTUAL_WIDTH - target.fw, nx))
                ny = max(0.0, min(VIRTUAL_HEIGHT - target.fh, ny))
            else:
                hero = state.resolver.resolve_hero_panel()
                nx = max(hero[0] - VIRTUAL_WIDTH, min(hero[0] + hero[2] + VIRTUAL_WIDTH - target.fw, nx))
                ny = max(hero[1] - VIRTUAL_HEIGHT, min(hero[1] + hero[3] + VIRTUAL_HEIGHT - target.fh, ny))
            target.set_position(nx, ny, state.resolver, state.doc)

    def component_at(pos):
        """Retorna o componente topmost sob o cursor, dentro da Ã¡rea de design."""
        if not design_rect.collidepoint(pos):
            return None
        for comp in reversed(state.components):
            sr = to_screen(comp.screen_rect())
            if sr.collidepoint(pos):
                return comp
        return None

    # ------------------------------------------------------------------
    # Overhead UI drag helpers
    # ------------------------------------------------------------------
    def cast_bar_rect():
        comp = state.selector_to_component.get('#cast-bar')
        if comp:
            r = comp.screen_rect()
            return (r.x, r.y, r.w, r.h)
        return (PLAYER_POS[0], PLAYER_POS[1], 420.0, 18.0)

    def overhead_bar_rect():
        import math
        comp = state.selector_to_component.get('#overhead-hp-sp')
        if comp:
            cx, cy = comp.screen_rect().center
        else:
            cx, cy = PLAYER_POS
        radius_x = 70.0
        radius_y = 28.0
        sp_rx = radius_x * 1.12
        sp_ry = radius_y * 1.12
        base = math.radians(overhead_arc_rotation)
        # Compute bounding box of the rotated semi-ellipse arc
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        steps = 16
        for i in range(steps + 1):
            a = math.pi + base + (math.pi * i / steps)
            x = math.cos(a) * sp_rx
            y = math.sin(a) * sp_ry
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
        total_w = max_x - min_x
        total_h = max_y - min_y
        x0 = cx + min_x
        y0 = cy + min_y
        return (x0, y0, total_w, total_h)

    def overhead_hit(pos):
        """Retorna 'cast' ou 'overhead' se o mouse estiver sobre um elemento overhead."""
        if not design_rect.collidepoint(pos):
            return None
        mx, my = to_virtual(pos[0], pos[1])
        cx, cy, cw, ch = cast_bar_rect()
        if cx <= mx <= cx + cw and cy <= my <= cy + ch:
            return 'cast'
        hx, hy, hw, hh = overhead_bar_rect()
        # área de hit um pouco maior para facilitar
        pad = 4.0
        if hx - pad <= mx <= hx + hw + pad and hy - pad <= my <= hy + hh + pad:
            return 'overhead'
        return None

    hovered_overhead = None

    running = True
    clock = pygame.time.Clock()
    dt = 0.0

    while running:
        mouse_x, mouse_y = pygame.mouse.get_pos()
        mouse_pos = (mouse_x, mouse_y)

        menu_height += (target_menu_height - menu_height) * 0.2
        if abs(menu_height - target_menu_height) < 1:
            menu_height = target_menu_height

        layer_panel.rect = layer_panel_rect()
        btn_snap.rect.topleft = (screen_width - layer_w() - 8 - 90, 6)
        btn_grid.rect.topleft = (screen_width - layer_w() - 8 - 180, 6)
        btn_bind_to_player.rect.topleft = (screen_width - layer_w() - 8 - 380, 6)

        for btn in buttons:
            btn.update(mouse_pos)
        for btn in menu_buttons:
            btn.update(mouse_pos)

        update_scale()
        design_rect = design_area_rect()

        # Sincroniza painel de layers com a seleÃ§Ã£o principal
        if state.selected_set:
            if layer_panel.selected not in state.selected_set:
                layer_panel.selected = next(iter(state.selected_set))
        else:
            layer_panel.selected = None

        # Hover de handle (somente entre widgets selecionados)
        hovered_comp = None
        hovered_handle = None
        for comp in reversed(state.components):
            if comp.selector in state.selected_set:
                hovered_handle = handle_at(mouse_pos, comp)
                if hovered_handle:
                    hovered_comp = comp
                    break

        # Hover de elementos overhead
        hovered_overhead = overhead_hit(mouse_pos)

        if hovered_handle:
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_SIZENWSE if hovered_handle in ('nw', 'se') else
                                    pygame.SYSTEM_CURSOR_SIZENESW if hovered_handle in ('ne', 'sw') else
                                    pygame.SYSTEM_CURSOR_SIZENS if hovered_handle in ('n', 's') else
                                    pygame.SYSTEM_CURSOR_SIZEWE)
        elif hovered_overhead:
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_HAND)
        else:
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)

        # Atualiza botão de bind conforme seleção atual
        update_bind_button()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.VIDEORESIZE:
                screen_width, screen_height = event.size
                screen = pygame.display.set_mode((screen_width, screen_height), pygame.RESIZABLE)
                update_scale()

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    handled = False
                    for btn in buttons:
                        if btn.handle_click(event.pos):
                            handled = True
                            break
                    if not handled and menu_open:
                        for btn in menu_buttons:
                            if btn.handle_click(event.pos):
                                handled = True
                                break
                        if not handled:
                            # clique fora do menu fecha-o sem selecionar widget
                            toggle_menu()
                            continue
                    if handled:
                        continue

                    # Painel de layers: inicia drag-and-drop de layer
                    if layer_panel.rect.collidepoint(event.pos) and show_layers:
                        if layer_panel.start_drag(event.pos):
                            state.select_only(layer_panel.selected)
                            continue

                    # Handles de redimensionamento primeiro (somente entre selecionados)
                    clicked_handle = None
                    handle_comp = None
                    for comp in reversed(state.components):
                        if comp.selector in state.selected_set:
                            hname = handle_at(event.pos, comp)
                            if hname:
                                clicked_handle = hname
                                handle_comp = comp
                                break
                    if clicked_handle and handle_comp:
                        handle_comp.resizing = True
                        handle_comp.resize_handle = clicked_handle
                        r = handle_comp.screen_rect()
                        handle_comp.resize_start_rect = (r.x, r.y, r.w, r.h)
                        handle_comp.resize_start_mouse = to_virtual(event.pos[0], event.pos[1])
                        continue

                    # Clique em componente: seleciona / toggle e inicia drag
                    comp = component_at(event.pos)
                    ctrl = pygame.key.get_mods() & pygame.KMOD_CTRL
                    if comp:
                        if ctrl:
                            state.toggle_select(comp.selector)
                        else:
                            state.select_only(comp.selector)
                        # Inicia drag de todos os selecionados
                        vx, vy = to_virtual(event.pos[0], event.pos[1])
                        for c in state.components:
                            if c.selector in state.selected_set:
                                c.dragging = True
                                r = c.screen_rect()
                                c.offset = (r.x - vx, r.y - vy)
                        if not lock_layer_order and len(state.selected_set) == 1:
                            for c in state.components:
                                if c.selector == comp.selector:
                                    state.components.remove(c)
                                    state.components.append(c)
                                    break
                    else:
                        # Clique em elemento overhead (área de hit maior que o rect CSS)?
                        hit = overhead_hit(event.pos)
                        if hit:
                            selector = '#cast-bar' if hit == 'cast' else '#overhead-hp-sp'
                            state.select_only(selector)
                            vx, vy = to_virtual(event.pos[0], event.pos[1])
                            for c in state.components:
                                if c.selector == selector:
                                    c.dragging = True
                                    r = c.screen_rect()
                                    c.offset = (r.x - vx, r.y - vy)
                                    break
                        elif not ctrl:
                            state.clear_selection()

                elif event.button == 4:
                    if layer_panel.rect.collidepoint(event.pos):
                        layer_panel.scroll = max(0, layer_panel.scroll - 1)
                elif event.button == 5:
                    if layer_panel.rect.collidepoint(event.pos):
                        layer_panel.scroll = min(max(0, len(state.components) - 1), layer_panel.scroll + 1)

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    if layer_panel.dragging_idx is not None:
                        layer_panel.end_drag()
                        state.sort_by_z()
                    for comp in state.components:
                        comp.dragging = False
                        comp.resizing = False
                        comp.resize_handle = None
                        comp.resize_start_rect = None
                        comp.resize_start_mouse = None

            elif event.type == pygame.MOUSEMOTION:
                if layer_panel.dragging_idx is not None:
                    layer_panel.update_drag(event.pos)
                    continue

                for comp in state.components:
                    if comp.resizing and comp.resize_handle:
                        mx, my = to_virtual(event.pos[0], event.pos[1])
                        apply_resize(comp, comp.resize_handle, mx, my)
                    elif comp.dragging:
                        vx, vy = to_virtual(event.pos[0], event.pos[1])
                        nx = vx + comp.offset[0]
                        ny = vy + comp.offset[1]
                        if snap_enabled:
                            nx = snap(nx, grid_size)
                            ny = snap(ny, grid_size)
                        # Converte posição visual para o espaço do componente
                        if comp.bind_to_player:
                            nx = max(PLAYER_POS[0] - 500.0, min(PLAYER_POS[0] + 500.0, nx))
                            ny = max(PLAYER_POS[1] - 500.0, min(PLAYER_POS[1] + 500.0, ny))
                        elif comp.is_top:
                            nx = max(0.0, min(VIRTUAL_WIDTH - comp.fw, nx))
                            ny = max(0.0, min(VIRTUAL_HEIGHT - comp.fh, ny))
                        else:
                            hero = state.resolver.resolve_hero_panel()
                            nx = max(hero[0] - VIRTUAL_WIDTH, min(hero[0] + hero[2] + VIRTUAL_WIDTH - comp.fw, nx))
                            ny = max(hero[1] - VIRTUAL_HEIGHT, min(hero[1] + hero[3] + VIRTUAL_HEIGHT - comp.fh, ny))
                        comp.set_position(nx, ny, state.resolver, state.doc)

            elif event.type == pygame.KEYDOWN:
                mods = pygame.key.get_mods()
                shift = mods & pygame.KMOD_SHIFT
                ctrl = mods & pygame.KMOD_CTRL
                step = 10.0 if shift else 1.0
                if event.key == pygame.K_g:
                    set_snap(not snap_enabled)
                elif event.key == pygame.K_UP:
                    nudge_selected(0, -step)
                elif event.key == pygame.K_DOWN:
                    nudge_selected(0, step)
                elif event.key == pygame.K_LEFT:
                    nudge_selected(-step, 0)
                elif event.key == pygame.K_RIGHT:
                    nudge_selected(step, 0)
                elif event.key == pygame.K_PAGEUP:
                    if ctrl:
                        layer_panel.move_selected(-1)
                elif event.key == pygame.K_PAGEDOWN:
                    if ctrl:
                        layer_panel.move_selected(1)
                elif event.key == pygame.K_e:
                    export()
                elif event.key == pygame.K_l:
                    toggle_layers()
                elif event.key == pygame.K_k:
                    set_lock_layer_order(not lock_layer_order)
                elif event.key == pygame.K_ESCAPE:
                    state.clear_selection()
                    layer_panel.selected = None
                elif event.key == pygame.K_b:
                    targets = [c for c in state.components if c.selector in state.selected_set]
                    if targets:
                        new_mode = not all(c.bind_to_player for c in targets)
                        toggle_bind_to_player(new_mode)
                elif event.key == pygame.K_EQUALS or event.key == pygame.K_PLUS:
                    adjust_zoom(-0.05)
                    zoom_key_held = event.key
                    zoom_key_timer = ZOOM_REPEAT_DELAY
                elif event.key == pygame.K_MINUS:
                    adjust_zoom(0.05)
                    zoom_key_held = event.key
                    zoom_key_timer = ZOOM_REPEAT_DELAY
                elif event.key == pygame.K_0:
                    set_zoom(1.0)
                elif event.key == pygame.K_LEFTBRACKET:
                    adjust_pitch(-PITCH_STEP)
                    pitch_key_held = event.key
                    pitch_key_timer = ZOOM_REPEAT_DELAY
                elif event.key == pygame.K_RIGHTBRACKET:
                    adjust_pitch(PITCH_STEP)
                    pitch_key_held = event.key
                    pitch_key_timer = ZOOM_REPEAT_DELAY
                elif event.key == pygame.K_p:
                    set_pitch(50.0)

            elif event.type == pygame.KEYUP:
                if event.key == zoom_key_held:
                    zoom_key_held = None
                    zoom_key_timer = 0.0
                if event.key == pitch_key_held:
                    pitch_key_held = None
                    pitch_key_timer = 0.0

        # Repetição contínua de zoom enquanto a tecla estiver segurada
        if zoom_key_held:
            zoom_key_timer -= dt
            if zoom_key_timer <= 0.0:
                if zoom_key_held in (pygame.K_EQUALS, pygame.K_PLUS):
                    adjust_zoom(-0.05)
                elif zoom_key_held == pygame.K_MINUS:
                    adjust_zoom(0.05)
                zoom_key_timer = ZOOM_REPEAT_INTERVAL

        # Repetição contínua de pitch enquanto a tecla estiver segurada
        if pitch_key_held:
            pitch_key_timer -= dt
            if pitch_key_timer <= 0.0:
                if pitch_key_held == pygame.K_LEFTBRACKET:
                    adjust_pitch(-PITCH_STEP)
                elif pitch_key_held == pygame.K_RIGHTBRACKET:
                    adjust_pitch(PITCH_STEP)
                pitch_key_timer = ZOOM_REPEAT_INTERVAL

        # Render
        screen.fill((18, 19, 22))

        # Top bar
        pygame.draw.rect(screen, (28, 30, 34), (0, 0, screen_width, top_bar_height))
        pygame.draw.line(screen, (139, 90, 43), (0, top_bar_height), (screen_width, top_bar_height), 2)

        # Menu dropdown
        if menu_height > 1:
            pygame.draw.rect(screen, (34, 36, 42), (0, top_bar_height, screen_width, int(menu_height)))
            pygame.draw.line(screen, (80, 70, 60), (0, top_bar_height + int(menu_height) - 1),
                             (screen_width, top_bar_height + int(menu_height) - 1), 1)

        for btn in buttons:
            btn.draw(screen, font)
        for btn in menu_buttons:
            btn.draw(screen, font)

        # Design area background
        pygame.draw.rect(screen, (22, 23, 26), design_rect)

        # Grid
        if show_grid:
            for x in range(design_rect.left, design_rect.right, int(grid_size * scale_x)):
                pygame.draw.line(screen, (45, 45, 50), (x, design_rect.top), (x, design_rect.bottom))
            for y in range(design_rect.top, design_rect.bottom, int(grid_size * scale_y)):
                pygame.draw.line(screen, (45, 45, 50), (design_rect.left, y), (design_rect.right, y))

        # Hero panel reference outline
        hero = state.resolver.resolve_hero_panel()
        hpsr = to_screen(pygame.Rect(int(hero[0]), int(hero[1]), int(hero[2]), int(hero[3])))
        if hpsr.colliderect(design_rect):
            pygame.draw.rect(screen, (107, 143, 94), hpsr, 2)
            label = font.render("Hero Panel (reference)", True, (107, 143, 94))
            screen.blit(label, (hpsr.x + 4, hpsr.y + 4))

        # Components: renderiza numa surface virtual e faz stretch para a área de design
        virtual_surf = pygame.Surface((int(VIRTUAL_WIDTH), int(VIRTUAL_HEIGHT)), pygame.SRCALPHA)
        virtual_surf.fill((0, 0, 0, 0))
        # Player placeholder primeiro: na engine o sprite e' mundo e a HUD (ImGui)
        # e' sempre desenhada por cima, inclusive as barras sobre a cabeca.
        renderer.draw_player_placeholder(virtual_surf, PLAYER_CENTER, PLAYER_BASE, PLAYER_SPRITE_H, dt)
        for comp in state.components:
            renderer.draw_component(virtual_surf, comp.selector, comp.screen_rect())

        # Loading bar reference (posição fixa da engine, não editável)
        renderer.draw_loading_bar_reference(virtual_surf)

        scaled_surf = pygame.transform.scale(virtual_surf, design_rect.size)
        screen.blit(scaled_surf, design_rect.topleft)

        for comp in state.components:
            sr = to_screen(comp.screen_rect())
            if not sr.colliderect(design_rect):
                continue
            is_selected = comp.selector in state.selected_set
            if is_selected:
                pygame.draw.rect(screen, (255, 220, 80), sr, 2)
                draw_handles(screen, comp)
            z_surf = font.render(f"z:{comp.z_index}", True, (255, 220, 80))
            screen.blit(z_surf, (sr.x + sr.w - z_surf.get_width() - 4, sr.y + 2))

        # Highlight extra para overhead (área do arco pode ser maior que o rect CSS)
        if hovered_overhead or state.selected_set & {'#cast-bar', '#overhead-hp-sp'}:
            for name, rect_func in [('cast', cast_bar_rect), ('overhead', overhead_bar_rect)]:
                selector = '#cast-bar' if name == 'cast' else '#overhead-hp-sp'
                is_selected = selector in state.selected_set
                if hovered_overhead == name or is_selected:
                    x, y, w, h = rect_func()
                    sr = to_screen(pygame.Rect(int(x), int(y), int(w), int(h)))
                    if sr.colliderect(design_rect):
                        color = (0, 180, 255) if hovered_overhead == name else (255, 220, 80)
                        pygame.draw.rect(screen, color, sr, 2)

        # Guides
        draw_guides(screen)

        # Layer panel
        if show_layers:
            layer_panel.draw(screen, font, header_font)

        # Message
        if message_timer > 0:
            msg_surf = msg_font.render(message, True, (100, 255, 100))
            msg_rect = msg_surf.get_rect(center=(screen_width // 2, 30))
            bg_rect = msg_rect.inflate(20, 10)
            pygame.draw.rect(screen, (0, 0, 0), bg_rect)
            pygame.draw.rect(screen, (255, 255, 255), bg_rect, 1)
            screen.blit(msg_surf, msg_rect)
            message_timer -= 1

        # Snap / Layers / Lock status
        selected_names = ", ".join(state.selector_to_component[s].name for s in state.selected_set)
        bind_mode = "-"
        if state.selected_set:
            targets = [state.selector_to_component[s] for s in state.selected_set]
            bind_mode = "Player" if all(c.bind_to_player for c in targets) else "HUD"
        status_text = (f"Snap: {'ON' if snap_enabled else 'OFF'} (G)   "
                       f"Layers: {'ON' if show_layers else 'OFF'} (L)   "
                       f"Lock: {'ON' if lock_layer_order else 'OFF'} (K)   "
                       f"Zoom: {(1.0 - (PLAYER_CAMERA_DISTANCE * player_zoom - 10.0) / 990.0) * 100.0:.0f}% (-/+/0)   "
                       f"Pitch: {player_pitch:.0f}° ([/]/P)   "
                       f"Sel: {selected_names or 'none'}   "
                       f"Bind: {bind_mode}")
        snap_text = font.render(status_text, True, (200, 200, 200))
        screen.blit(snap_text, (8, screen_height - 20))

        pygame.display.flip()
        # CALDERA_SCREENSHOT=/caminho.png: salva o quadro apos alguns frames e sai
        # (uso: conferir o layout sem abrir a janela, ex. sob Xvfb).
        _shot = os.environ.get('CALDERA_SCREENSHOT')
        if _shot:
            _frames = globals().get('_shot_frames', 0) + 1
            globals()['_shot_frames'] = _frames
            if _frames >= 5:
                pygame.image.save(screen, _shot)
                return
        dt = clock.tick(60) / 1000.0

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()

"""Rotating public-domain artwork for briefing editions.

A curated pool of landscape paintings (Wikimedia Commons, public domain). Each
user's edition draws one deterministically from ``pick_artwork`` so the artwork
is stable for a given seed yet varies across users and days — no two users get
the same painting on the same day (with a large enough pool; some overlap is
expected and fine). Seed with ``f"{{user_id}}:{{date}}"`` for daily variation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib


@dataclass(frozen=True)
class Artwork:
    url: str
    title: str


_ARTWORK_POOL: tuple[Artwork, ...] = (
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/b/b1/%22Il_faut_barrer_la_route%22.jpg/1920px-%22Il_faut_barrer_la_route%22.jpg",
        title='\\"Il faut barrer la route\\"',
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/6/64/%22Nubes_del_verano%22.jpg",
        title='\\"Nubes del verano\\"',
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/8/87/%22O_Areinho%22_-_Sofia_Martins_de_Sousa.png",
        title='\\"O Areinho\\" - Sofia Martins de Sousa',
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/0/0c/%22Paisaje_de_Pampliega%22%2C_Juan_Etxebarria.PNG",
        title='\\"Paisaje de Pampliega\\", Juan Etxebarria',
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/0/0a/%22Paisaje_rojo_II%22_de_Teresa_Casas.jpg/1920px-%22Paisaje_rojo_II%22_de_Teresa_Casas.jpg",
        title='\\"Paisaje rojo II\\" de Teresa Casas',
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/%22Quito%22_%281860%29%2C_%C3%B3leo_sobre_lienzo_atribuido_a_Rafael_Salas_Estrada.jpg/1920px-%22Quito%22_%281860%29%2C_%C3%B3leo_sobre_lienzo_atribuido_a_Rafael_Salas_Estrada.jpg",
        title='\\"Quito\\" (1860), óleo sobre lienzo atribuido a Rafael Salas Estrada',
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/1/13/%22View_of_the_Female_Orphan_School%2C_Near_Parramatta%22_-_Joseph_Lycett_%28c1825%29.jpg",
        title='\\"View of the Female Orphan School, Near Parramatta\\" - Joseph Lycett (c1825)',
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/8/80/%22Warren_Road%22_oil_painting.jpg",
        title='\\"Warren Road\\" oil painting',
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/f/fc/%27LANDSCAPE_WITH_OLD_TRUCK%27_OIL_PAINTING_BY_JAIME_PROSSER.jpg/1920px-%27LANDSCAPE_WITH_OLD_TRUCK%27_OIL_PAINTING_BY_JAIME_PROSSER.jpg",
        title="'LANDSCAPE WITH OLD TRUCK' OIL PAINTING BY JAIME PROSSER",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/d/de/%27SHEARING_TIME_AGAIN%27_OIL_PAINTING_BY_JAIME_PROSSER.jpg",
        title="'SHEARING TIME AGAIN' OIL PAINTING BY JAIME PROSSER",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/a/a0/...T%C3%AFpico_de_Costa_Rica.....jpg",
        title="...Tïpico de Costa Rica....",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/e/ee/011849-000_Immensitat.jpg/1920px-011849-000_Immensitat.jpg",
        title="011849-000 Immensitat",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/6/6d/Valerius_de_Saedeleer_-_Before_spring.jpg",
        title="Valerius de Saedeleer - Before spring",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/1/1e/11.09_Ausencia.JPG/1920px-11.09_Ausencia.JPG",
        title="11.09 Ausencia",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/6/6c/15._%CE%BA%CE%BF%CF%81%CF%85%CF%84%CF%83%CE%AC_1940_%280%2C43%CF%870%2C51%29.jpg",
        title="15. κορυτσά 1940 (0,43χ0,51)",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/6/66/1561_ARTUR_NIKODEM_Landschaft_mit_Birken_ca_1925.jpg",
        title="1561 ARTUR NIKODEM Landschaft mit Birken ca 1925",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/c/cc/17-CHARENTE_MARITIME-La_Rochelle-20F-2018.jpg/1920px-17-CHARENTE_MARITIME-La_Rochelle-20F-2018.jpg",
        title="17-CHARENTE MARITIME-La Rochelle-20F-2018",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/7/7c/Jasper_Broers_-_Cavalry_Skirmish_in_front_of_a_Ruined_Temple.jpg/1920px-Jasper_Broers_-_Cavalry_Skirmish_in_front_of_a_Ruined_Temple.jpg",
        title="Jasper Broers - Cavalry Skirmish in front of a Ruined Temple",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/6/6a/Jasper_Broers_-_Cavalry_Skirmish_in_front_of_a_Tomb.jpg/1920px-Jasper_Broers_-_Cavalry_Skirmish_in_front_of_a_Tomb.jpg",
        title="Jasper Broers - Cavalry Skirmish in front of a Tomb",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/3/3d/Marszewski_Vilnius_surroundings.jpg",
        title="Marszewski Vilnius surroundings",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/c/c5/1877_sc%C3%A8ne_anim%C3%A9e.jpg",
        title="1877 scène animée",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/6/65/1896_Lebeda_Bergsee_in_den_Giant_Mountains_Nationalgalerie_Prag_anagoria.jpg/1920px-1896_Lebeda_Bergsee_in_den_Giant_Mountains_Nationalgalerie_Prag_anagoria.jpg",
        title="1896 Lebeda Bergsee in den Giant Mountains Nationalgalerie Prag anagoria",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/2/28/1901_Phokas_Paysage_National_Gallery_of_Greece_-_Corfu_Annex_anagoria.jpg/1920px-1901_Phokas_Paysage_National_Gallery_of_Greece_-_Corfu_Annex_anagoria.jpg",
        title="1901 Phokas Paysage National Gallery of Greece - Corfu Annex anagoria",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/7/70/Samuel_Hirszenberg_-_Krajobraz_z_je%C5%BAd%C5%BAcem.jpg",
        title="Samuel Hirszenberg - Krajobraz z jeźdźcem",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/a/a6/Samuel_Hirszenberg_-_Pejza%C5%BC_ze_scen%C4%85_rodzajow%C4%85.jpg/1920px-Samuel_Hirszenberg_-_Pejza%C5%BC_ze_scen%C4%85_rodzajow%C4%85.jpg",
        title="Samuel Hirszenberg - Pejzaż ze sceną rodzajową",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/8/87/1905_Ameseder_Vor_dem_Sturm_Nationalgalerie_Prag_anagoria.jpg/1920px-1905_Ameseder_Vor_dem_Sturm_Nationalgalerie_Prag_anagoria.jpg",
        title="1905 Ameseder Vor dem Sturm Nationalgalerie Prag anagoria",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/4/48/1935_Alberts_Bl%C3%BChende_Hallig_anagoria.JPG/1920px-1935_Alberts_Bl%C3%BChende_Hallig_anagoria.JPG",
        title="1935 Alberts Blühende Hallig anagoria",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/d/db/1mb_scape_0416_s.jpg",
        title="1mb scape 0416 s",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/d/df/2_-_2016_Wasserm%C3%BChle_-F._Austermann.jpg/1920px-2_-_2016_Wasserm%C3%BChle_-F._Austermann.jpg",
        title="2 - 2016 Wassermühle -F. Austermann",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/2/2a/2010_Utopien_arche04.jpg",
        title="2010 Utopien arche04",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/7/7c/2011.1.5_PS6.jpg/1920px-2011.1.5_PS6.jpg",
        title="2011.1.5 PS6",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/e/e2/2012PaulViaccozAvalancheAcrylCrayonSurBois342x450cmMuseeArtHistoireGeCollFMAC.jpg",
        title="2012PaulViaccozAvalancheAcrylCrayonSurBois342x450cmMuseeArtHistoireGeCollFMAC",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/8/84/2018-0251-1600x1200.jpg",
        title="2018-0251-1600x1200",
    ),
    Artwork(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/9/97/2018-03-28_pepper_carrot_The-rendezvous_by-David-Revoy.jpg/1920px-2018-03-28_pepper_carrot_The-rendezvous_by-David-Revoy.jpg",
        title="2018-03-28 pepper carrot The-rendezvous by-David-Revoy",
    ),
)


def pick_artwork(seed: str) -> Artwork:
    """Deterministically pick one artwork from the pool for ``seed``.

    Same seed -> same artwork; different seeds spread across the pool. Seed with
    ``f"{user_id}:{date}"`` so a user gets a fresh painting each day and two
    users rarely share one on the same day.
    """
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    idx = int.from_bytes(digest[:8], "big") % len(_ARTWORK_POOL)
    return _ARTWORK_POOL[idx]


def pool_size() -> int:
    return len(_ARTWORK_POOL)

# /// script
# dependencies = ["fonttools==4.68.0", "brotli==1.2.1", "httpx==0.28.1"]
# ///
"""Build the brief editions' webfonts into app/services/briefing/editions/fonts/.

Downloads each approved face from a pinned source (verified by SHA-256), instances
the variable ones at the cuts the edition templates print, subsets them to Latin
and writes WOFF2 files, their licences and fonts.json (the faces explorer_render.py
embeds, with each source's URL, version and hash). Aeonik is copied as-is from the
web app. Rerunning it reproduces the checked-in files byte for byte.

Usage (from the repo root)::

    uv run apps/api/scripts/build_edition_fonts.py
"""

from dataclasses import dataclass, field
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unicodedata

from fontTools import subset
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
import httpx

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "apps/api/app/services/briefing/editions/fonts"
AEONIK = REPO / "apps/web/src/app/fonts/aeonik"

GF = "https://raw.githubusercontent.com/google/fonts/5bb28733cec313b63fbd415b574b5ae35c8aa8b8/"
CTAN = "https://mirrors.ctan.org/fonts/tex-gyre/"

# Every downloaded file, pinned: a source that changes upstream fails the build.
SHA256 = {
    CTAN
    + "opentype/texgyreheros-regular.otf": "6ae1a09d5a940367b7aaaa91ee8bd8a2c333bfe193e7096e23f931357d62081f",
    CTAN
    + "opentype/texgyreheros-bold.otf": "b170162835f4efc288886dd4231406dc47e19b614cf4416836635599d44a7d60",
    CTAN
    + "opentype/texgyreheros-italic.otf": "6473df7fa107b3fb4be38973710afe22b0640c2ac076d5337cf126bed9aa108c",
    CTAN
    + "doc/GUST-FONT-LICENSE.txt": "2bd69affc3da00715116f713f57eab9707e96daf3562ad0215987b15b9c16f73",
    GF
    + "ofl/librebaskerville/LibreBaskerville[wght].ttf": "05a95421961341c5b2556285e8415df9db27dab4f4abe22b446b3c6a8b916c5d",
    GF
    + "ofl/librebaskerville/LibreBaskerville-Italic[wght].ttf": "223959683dc73ec4437bd61fabaa4b3f22209e22855ffd3aee36ba61a5116e97",
    GF
    + "ofl/librebaskerville/OFL.txt": "3624eddd4c8f8a908130a417ae7cd089c9da69899c4e0ca1a5217d0a6fae16fd",
    GF
    + "ofl/librecaslondisplay/LibreCaslonDisplay-Regular.ttf": "2340c497181e9446fcbb235e1c3780558dc62879ffe0ef47906d3f7f35cf5f35",
    GF
    + "ofl/librecaslondisplay/OFL.txt": "9cc8cef15f5e8bcbe99a13ee8d268f6f6f6a5811cd1ed05056ef4608c9b16fd1",
    GF
    + "ofl/librecaslontext/LibreCaslonText[wght].ttf": "c11809dbfd5445886293d89b32bfc2584075c80e77750cf1c284113e36b8b3f4",
    GF
    + "ofl/librecaslontext/LibreCaslonText-Italic[wght].ttf": "60ca1a3aade61c8c381800ca85b9b2f0fb341d89ebe065e12cd6ec2ee2e53e54",
    GF
    + "ofl/librecaslontext/OFL.txt": "a294245c822c5aa9fd9a9f3189418e99415428be5fecadf797793d5d8f6a3ad3",
    GF
    + "ofl/sourceserif4/SourceSerif4[opsz,wght].ttf": "97b2d4da6e3cb494b5a1e66ae176914d852ccabef49e0c02c0df25f3e39aca0b",
    GF
    + "ofl/sourceserif4/SourceSerif4-Italic[opsz,wght].ttf": "15fbc7e4679489a501998c3669272637a6646388ef7e4bd77eebb5bf967a1f42",
    GF
    + "ofl/sourceserif4/OFL.txt": "5f94c3fd3a23131a417ab5a0c8452de57e70c3cfb9f604d88241f7065ebf9fd9",
    GF
    + "ofl/bodonimoda/BodoniModa[opsz,wght].ttf": "550f5e34ee0a828d7941b1fe9bc58b34e5260d3f33a61532e6d0a0114e79a5cf",
    GF
    + "ofl/bodonimoda/BodoniModa-Italic[opsz,wght].ttf": "dfff1619f8f6871c6372f8855b67211f9a73b4e93d45aca868cd8f46a48622de",
    GF
    + "ofl/bodonimoda/OFL.txt": "931dfe2e0cd3c9443295f5c1d754b8a8403bf060df50c1d5900267ade83d0046",
    GF
    + "ofl/barlowcondensed/BarlowCondensed-Regular.ttf": "583cec5da3b84bc4dc7c9c72e2a565c94d34e431518b19d7e250b7830ad5f996",
    GF
    + "ofl/barlowcondensed/BarlowCondensed-SemiBold.ttf": "7b619d14bc2327509a9ef32b0890f709626f7ecc9ff61191c2a4314c5499d2d9",
    GF
    + "ofl/barlowcondensed/BarlowCondensed-Bold.ttf": "e476562ec9c1e16cf16475895b511f08c804f438cc9a9f80a44ea50a0eeb5b65",
    GF
    + "ofl/barlowcondensed/OFL.txt": "186d750eb496a4c17a76385f82be6aea2ac1cf2de074a811d63786cf374ea73f",
    GF
    + "ofl/jetbrainsmono/JetBrainsMono[wght].ttf": "48715a42ec242c21e9f02692891e147d022299a52e48d5e413e1a942193ffeda",
    GF
    + "ofl/jetbrainsmono/OFL.txt": "b2fe5e8987594e9ffd1d2ca52a2f5d73eb8335243893c5d6254b5ad69269591d",
    GF
    + "ofl/schibstedgrotesk/SchibstedGrotesk[wght].ttf": "6ceeadf6be8e1fd7687011c7fa38ed0edd1abe967a0b73d97caec183552e823d",
    GF
    + "ofl/schibstedgrotesk/OFL.txt": "3b4f3063b6ac7c1e403e2c4a5e8ef3a58190ff83ed7b15af66511858699139ce",
    GF
    + "ofl/sofiasanscondensed/SofiaSansCondensed[wght].ttf": "3282c4e1a09d14e91c5fdb10aadee93048d017fa00f857f43fdcc29c989221fd",
    GF
    + "ofl/sofiasanscondensed/OFL.txt": "3e824d5099202de2c98cbd8e5ecba54da7d220c1ad851330726e65f3e60842d1",
    GF
    + "apache/specialelite/SpecialElite-Regular.ttf": "a776fcb4ceb8bdf03e2967688ebdad42680de5b91a7e62c17e718ae212d14bc4",
    GF
    + "apache/specialelite/LICENSE.txt": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    GF
    + "ofl/pinyonscript/PinyonScript-Regular.ttf": "4aab130a6ed27f8b8117738c84a5602edf9300cdcc0651a9a65bf96f451ac29a",
    GF
    + "ofl/pinyonscript/OFL.txt": "61d07cb0eaa943943648df2b11d0c2210e772053c192871e13f680b53fe0b77e",
    GF
    + "ofl/courierprime/CourierPrime-Regular.ttf": "72f793376f8e2841656bf21d77a5de010f2929bd6956a22ee848ad0c7eb978af",
    GF
    + "ofl/courierprime/CourierPrime-Bold.ttf": "ff1f38786c849d1c41fa8e447960abdb2bd75fdfb0cfcdeb524fad65a5af3638",
    GF
    + "ofl/courierprime/OFL.txt": "9a755af092b494944c99f471be6fddd19b006a448fefdc4717e4ee0aa09a97b0",
    GF
    + "ofl/cormorant/Cormorant[wght].ttf": "8f12cb21f05b61649192eaff13eeeb1b5619bc524feeae672fb916974259a076",
    GF
    + "ofl/cormorant/Cormorant-Italic[wght].ttf": "2c4e1c43fa126b51a84160815b9264af442c6c531d13bfd3c1723703cd489dd2",
    GF
    + "ofl/cormorant/OFL.txt": "60700d351cac4650c51f3f9db318d2a420f8b45052dba2715eb5fec41f0f6956",
    GF
    + "ofl/ebgaramond/EBGaramond[wght].ttf": "ef9512f92f6d579e5dc75af59a5a4b1b8b47d2eda89e00b954d44520e5369027",
    GF
    + "ofl/ebgaramond/EBGaramond-Italic[wght].ttf": "bba2c4499c93c9612b90b9825d32b07da52fce2fe57562a1eb6b833553f93c4e",
    GF
    + "ofl/ebgaramond/OFL.txt": "0985066662eb755ed3683ae5482a81a9195b49ce3f7e165cc2388b3dbece7dd7",
    GF
    + "ofl/overpass/Overpass[wght].ttf": "970717df17a7f9911dee45f60695d05bfa9d745fa0a11fc5c348371fa21f0073",
    GF + "ofl/overpass/OFL.txt": "86e5ff25c701ec446d20b1a85b02ee6d36de8503a7288a4c948f5459809af1f0",
    GF
    + "ofl/playfairdisplay/PlayfairDisplay[wght].ttf": "c40f2293766a503bc70cce9e512ef844a4ccb7cbcde792fe2ea31d191917d8d6",
    GF
    + "ofl/playfairdisplay/PlayfairDisplay-Italic[wght].ttf": "a5e26dc5e2e77fb2803a0bf02fd4f81ee136ec8dea863ccdb0c59a263b21378b",
    GF
    + "ofl/playfairdisplay/OFL.txt": "566be814f8e96e93dfa16101331557eb6b5467e9e03f627c0910fe93ca12300e",
    GF
    + "ofl/literata/Literata[opsz,wght].ttf": "b41138c9373112f32abb589cc22e8674b06ed4048b0c513be922bdd26f274440",
    GF
    + "ofl/literata/Literata-Italic[opsz,wght].ttf": "d483dfaeba9cbf4ce71d32a52ee65df82f7e35b15fff8d1011cdb242d1fcd465",
    GF + "ofl/literata/OFL.txt": "8742963604cd89dc81437811a850018fc03b2bfad686d7422c8235967c87614e",
    GF
    + "ofl/cutive/Cutive-Regular.ttf": "8f0eb3280328c0051bbe725ce9d68c9117484b769cf68dbacec4343ae92ee031",
    GF + "ofl/cutive/OFL.txt": "65a69f7322cb0f78169312f3656ac11b23f052fe2500d091ee04ca31535cc47a",
    GF
    + "ofl/newsreader/Newsreader[opsz,wght].ttf": "8a08d13f8a6c0d51be379a60af84f945f65369a67e509ee3c3bdcc421254d7c1",
    GF
    + "ofl/newsreader/Newsreader-Italic[opsz,wght].ttf": "796668611f80b64d5adf182fde3b6f29ed83b4e7cbec7b96937e84ac01364792",
    GF
    + "ofl/newsreader/OFL.txt": "fdfad38143ec470553cae82a1e45320bdd1b9ec70415d37bd0171051d8a4ded8",
}


@dataclass(frozen=True)
class Cut:
    weight: int
    italic: bool
    url: str
    # Variable axes other than wght, pinned for this cut; wght is pinned to the weight.
    pins: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Face:
    family: str
    cuts: tuple[Cut, ...]
    # Licence file name (without .txt) -> its source URL.
    licences: dict[str, str]
    # Scales the face to the measure of the system face it replaced (CSS size-adjust, %).
    size_adjust: int | None = None


def gf_variable(
    directory: str, stem: str, cuts: tuple[tuple[int, bool], ...], pins: dict[str, float]
) -> tuple[Cut, ...]:
    """Instance cuts of a Google Fonts variable family (roman stem.ttf, italic stem-Italic.ttf)."""
    axes = stem.partition("[")[2]
    roman = f"{GF}ofl/{directory}/{stem.partition('[')[0]}[{axes}"
    italic = f"{GF}ofl/{directory}/{stem.partition('[')[0]}-Italic[{axes}"
    return tuple(Cut(w, i, italic if i else roman, pins) for w, i in cuts)


def ofl(directory: str) -> str:
    return f"{GF}ofl/{directory}/OFL.txt"


ROMAN, ITALIC = False, True
# Only the cuts a template prints: CSS matches any other weight to its nearest real cut,
# and a face with no italic (Cutive, Special Elite) is slanted by the browser.
FACES: tuple[Face, ...] = (
    Face(
        "TeX Gyre Heros",
        (
            Cut(400, ROMAN, CTAN + "opentype/texgyreheros-regular.otf"),
            Cut(700, ROMAN, CTAN + "opentype/texgyreheros-bold.otf"),
            Cut(400, ITALIC, CTAN + "opentype/texgyreheros-italic.otf"),
        ),
        {"GUST-FONT-LICENSE": CTAN + "doc/GUST-FONT-LICENSE.txt"},
    ),
    Face(
        "Libre Baskerville",
        gf_variable(
            "librebaskerville", "LibreBaskerville[wght].ttf", ((400, ROMAN), (400, ITALIC)), {}
        ),
        {"OFL-Libre-Baskerville": ofl("librebaskerville")},
    ),
    # One CSS family over two Caslons: Display for the roman nameplate, Text for bold and italic.
    Face(
        "Broadsheet Caslon",
        (
            Cut(400, ROMAN, GF + "ofl/librecaslondisplay/LibreCaslonDisplay-Regular.ttf"),
            *gf_variable(
                "librecaslontext", "LibreCaslonText[wght].ttf", ((700, ROMAN), (400, ITALIC)), {}
            ),
        ),
        {
            "OFL-Libre-Caslon-Display": ofl("librecaslondisplay"),
            "OFL-Libre-Caslon-Text": ofl("librecaslontext"),
        },
    ),
    Face(
        "Source Serif 4",
        gf_variable(
            "sourceserif4",
            "SourceSerif4[opsz,wght].ttf",
            ((400, ROMAN), (700, ROMAN), (400, ITALIC), (500, ITALIC), (600, ITALIC)),
            {"opsz": 20},
        ),
        {"OFL-Source-Serif-4": ofl("sourceserif4")},
    ),
    Face(
        "Bodoni Moda",
        gf_variable(
            "bodonimoda", "BodoniModa[opsz,wght].ttf", ((400, ROMAN), (400, ITALIC)), {"opsz": 28}
        ),
        {"OFL-Bodoni-Moda": ofl("bodonimoda")},
    ),
    Face(
        "Barlow Condensed",
        tuple(
            Cut(weight, ROMAN, f"{GF}ofl/barlowcondensed/BarlowCondensed-{name}.ttf")
            for weight, name in ((400, "Regular"), (600, "SemiBold"), (700, "Bold"))
        ),
        {"OFL-Barlow-Condensed": ofl("barlowcondensed")},
    ),
    Face(
        "JetBrains Mono",
        gf_variable(
            "jetbrainsmono",
            "JetBrainsMono[wght].ttf",
            ((400, ROMAN), (600, ROMAN), (700, ROMAN)),
            {},
        ),
        {"OFL-JetBrains-Mono": ofl("jetbrainsmono")},
    ),
    Face(
        "Schibsted Grotesk",
        gf_variable("schibstedgrotesk", "SchibstedGrotesk[wght].ttf", ((700, ROMAN),), {}),
        {"OFL-Schibsted-Grotesk": ofl("schibstedgrotesk")},
    ),
    Face(
        "Sofia Sans Condensed",
        gf_variable(
            "sofiasanscondensed",
            "SofiaSansCondensed[wght].ttf",
            ((400, ROMAN), (700, ROMAN), (800, ROMAN)),
            {},
        ),
        {"OFL-Sofia-Sans-Condensed": ofl("sofiasanscondensed")},
    ),
    Face(
        "Special Elite",
        (Cut(400, ROMAN, GF + "apache/specialelite/SpecialElite-Regular.ttf"),),
        {"Apache-2.0-Special-Elite": GF + "apache/specialelite/LICENSE.txt"},
    ),
    # A script is already slanted: its one cut answers the italic request.
    Face(
        "Pinyon Script",
        (Cut(400, ITALIC, GF + "ofl/pinyonscript/PinyonScript-Regular.ttf"),),
        {"OFL-Pinyon-Script": ofl("pinyonscript")},
    ),
    Face(
        "Courier Prime",
        (
            Cut(400, ROMAN, GF + "ofl/courierprime/CourierPrime-Regular.ttf"),
            Cut(700, ROMAN, GF + "ofl/courierprime/CourierPrime-Bold.ttf"),
        ),
        {"OFL-Courier-Prime": ofl("courierprime")},
    ),
    Face(
        "Cormorant",
        gf_variable("cormorant", "Cormorant[wght].ttf", ((400, ROMAN), (400, ITALIC)), {}),
        {"OFL-Cormorant": ofl("cormorant")},
    ),
    Face(
        "EB Garamond",
        gf_variable("ebgaramond", "EBGaramond[wght].ttf", ((400, ROMAN), (400, ITALIC)), {}),
        {"OFL-EB-Garamond": ofl("ebgaramond")},
    ),
    Face(
        "Overpass",
        gf_variable(
            "overpass", "Overpass[wght].ttf", ((400, ROMAN), (500, ROMAN), (700, ROMAN)), {}
        ),
        {"OFL-Overpass": ofl("overpass")},
    ),
    Face(
        "Playfair Display",
        gf_variable(
            "playfairdisplay", "PlayfairDisplay[wght].ttf", ((700, ROMAN), (500, ITALIC)), {}
        ),
        {"OFL-Playfair-Display": ofl("playfairdisplay")},
    ),
    Face(
        "Literata",
        gf_variable(
            "literata",
            "Literata[opsz,wght].ttf",
            ((400, ROMAN), (400, ITALIC)),
            {"opsz": 18},
        ),
        {"OFL-Literata": ofl("literata")},
    ),
    # Cutive sets 20% wider than American Typewriter: scaled to its measure, the envelope keeps its lines.
    Face(
        "Cutive",
        (Cut(400, ROMAN, GF + "ofl/cutive/Cutive-Regular.ttf"),),
        {"OFL-Cutive": ofl("cutive")},
        size_adjust=83,
    ),
    Face(
        "Newsreader",
        gf_variable(
            "newsreader",
            "Newsreader[opsz,wght].ttf",
            ((700, ROMAN), (500, ITALIC)),
            {"opsz": 36},
        ),
        {"OFL-Newsreader": ofl("newsreader")},
    ),
)

# Aeonik Extended, copied byte for byte from the web app's own files.
AEONIK_FAMILY = "Aeonik Extended"
AEONIK_CUTS = {600: "AeonikExtendedProTRIAL-SemiBold.woff2", 700: "AeonikExtendedPro-Bold.woff2"}

# Latin: Basic Latin, Latin-1, Latin Extended-A, and the punctuation and signs a brief prints.
TEXT = (
    set(range(0x20, 0x7F))
    | set(range(0xA0, 0x180))
    | set(range(0x2010, 0x2028))
    | set(range(0x2030, 0x203B))
    | {0x2009, 0x200A, 0x202F, 0x2044, 0x20AC, 0x2122, 0x2190, 0x2191, 0x2192, 0x2193}
    | {0x2212, 0x2215}
)
FEATURES = ["kern", "liga", "clig", "calt", "ccmp", "locl", "mark", "mkmk", "tnum", "lnum"]
FEATURES += ["pnum", "onum", "case", "smcp", "c2sc", "frac", "sups"]


# GDEF glyph classes.
BASE_CLASS, MARK_CLASS = 1, 3


def fetch(url: str, cache: Path) -> Path:
    """Download a source once into cache and fail unless it matches its pinned hash."""
    dest = cache / hashlib.sha256(url.encode()).hexdigest()
    if not dest.exists():
        response = httpx.get(url, follow_redirects=True, timeout=60)
        response.raise_for_status()
        dest.write_bytes(response.content)
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    if digest != SHA256[url]:
        raise ValueError(f"{url} changed upstream: sha256 {digest}, pinned {SHA256[url]}")
    return dest


def file_name(family: str, weight: int, italic: bool) -> str:
    return f"{family.lower().replace(' ', '-')}-{weight}{'i' if italic else ''}.woff2"


def fix_vertical_metrics(font: TTFont) -> None:
    """Set OS/2 cap and x height from the H and x outlines: CSS cap and ex units read them."""
    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    os2 = font["OS/2"]
    os2.version = max(os2.version, 2)
    for char, attr in (("H", "sCapHeight"), ("x", "sxHeight")):
        pen = BoundsPen(glyphs)
        glyphs[cmap[ord(char)]].draw(pen)
        setattr(os2, attr, round(pen.bounds[3]))


def unmark_spacing_glyphs(font: TTFont) -> None:
    """Class spacing characters as base glyphs: Overpass marks its middle dot, which then draws with no advance."""
    if "GDEF" not in font or font["GDEF"].table.GlyphClassDef is None:
        return
    classes = font["GDEF"].table.GlyphClassDef.classDefs
    for codepoint, glyph in font.getBestCmap().items():
        if classes.get(glyph) == MARK_CLASS and unicodedata.category(chr(codepoint)) not in (
            "Mn",
            "Me",
        ):
            classes[glyph] = BASE_CLASS


def build_cut(cut: Cut, cache: Path) -> tuple[bytes, str]:
    """Return the cut's subset WOFF2 bytes and its source's version string."""
    font = TTFont(fetch(cut.url, cache))
    version = str(font["name"].getDebugName(5))
    if "fvar" in font:
        axes = {axis.axisTag for axis in font["fvar"].axes}
        pins = {**cut.pins, "wght": float(cut.weight)}
        font = instancer.instantiateVariableFont(
            font, {tag: value for tag, value in pins.items() if tag in axes}, updateFontNames=False
        )
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = FEATURES
    options.name_IDs = ["*"]
    options.notdef_outline = True
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=sorted(TEXT))
    subsetter.subset(font)
    fix_vertical_metrics(font)
    unmark_spacing_glyphs(font)
    buffer = io.BytesIO()
    font.flavor = "woff2"
    # Keep the source's head.modified: a rebuild reproduces the same bytes.
    font.recalcTimestamp = False
    font.save(buffer)
    return buffer.getvalue(), version


def face_entry(
    family: str, name: str, weight: int, italic: bool, size_adjust: int | None
) -> dict[str, object]:
    return {
        "family": family,
        "file": name,
        "weight": weight,
        "style": "italic" if italic else "normal",
        "size_adjust": size_adjust,
    }


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    faces: list[dict[str, object]] = []
    sources: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp)
        for face in FACES:
            for cut in face.cuts:
                data, version = build_cut(cut, cache)
                name = file_name(face.family, cut.weight, cut.italic)
                (OUT / name).write_bytes(data)
                faces.append(
                    face_entry(face.family, name, cut.weight, cut.italic, face.size_adjust)
                )
                sources.append(
                    {
                        "file": name,
                        "url": cut.url,
                        "sha256": SHA256[cut.url],
                        "version": version,
                        "pins": {**cut.pins, "wght": cut.weight},
                    }
                )
                print(f"{name:40} {len(data) / 1024:6.1f} KB  {version}")
            for label, url in face.licences.items():
                shutil.copyfile(fetch(url, cache), OUT / f"{label}.txt")
    for weight, source_name in AEONIK_CUTS.items():
        name = file_name(AEONIK_FAMILY, weight, False)
        shutil.copyfile(AEONIK / source_name, OUT / name)
        faces.append(face_entry(AEONIK_FAMILY, name, weight, False, None))
        sources.append({"file": name, "url": f"apps/web/src/app/fonts/aeonik/{source_name}"})
    manifest = {"faces": faces, "sources": sources}
    (OUT / "fonts.json").write_text(json.dumps(manifest, indent=1) + "\n")
    total = sum(path.stat().st_size for path in OUT.glob("*.woff2"))
    print(f"{len(faces)} faces, {total / 1024:.1f} KB of WOFF2")


if __name__ == "__main__":
    main()

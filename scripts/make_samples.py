"""Generate the two sample files in samples/: a KML and a zipped Shapefile.

Run from the repository root:  python scripts/make_samples.py
Both files describe made up plots near Bengaluru (EPSG:4326).
"""

import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon, box

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples"

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Sample survey</name>
    <Folder>
      <name>Plots</name>
      <Placemark>
        <name>Plot A</name>
        <ExtendedData><Data name="owner"><value>Ravi</value></Data></ExtendedData>
        <Polygon><outerBoundaryIs><LinearRing><coordinates>
          77.5900,12.9700 77.6000,12.9700 77.6000,12.9800 77.5900,12.9800 77.5900,12.9700
        </coordinates></LinearRing></outerBoundaryIs></Polygon>
      </Placemark>
      <Placemark>
        <name>Plot B (with a pond)</name>
        <Polygon>
          <outerBoundaryIs><LinearRing><coordinates>
            77.6100,12.9700 77.6200,12.9700 77.6200,12.9800 77.6100,12.9800 77.6100,12.9700
          </coordinates></LinearRing></outerBoundaryIs>
          <innerBoundaryIs><LinearRing><coordinates>
            77.6130,12.9730 77.6170,12.9730 77.6170,12.9770 77.6130,12.9770 77.6130,12.9730
          </coordinates></LinearRing></innerBoundaryIs>
        </Polygon>
      </Placemark>
    </Folder>
    <Folder>
      <name>Infrastructure</name>
      <Placemark>
        <name>Access road</name>
        <LineString><coordinates>
          77.5900,12.9650 77.5950,12.9690 77.6050,12.9690 77.6150,12.9650
        </coordinates></LineString>
      </Placemark>
      <Placemark>
        <name>Main gate</name>
        <Point><coordinates>77.5950,12.9690,0</coordinates></Point>
      </Placemark>
    </Folder>
  </Document>
</kml>
"""


def make_kml() -> Path:
    path = OUT / "survey.kml"
    path.write_text(KML, encoding="utf-8")
    return path


def make_shapefile_zip() -> Path:
    parcels = gpd.GeoDataFrame(
        {
            "plot_id": [1, 2, 3, 4],
            "owner": ["Asha", "Kiran", "Meera", "Naveen"],
            "land_use": ["residential", "farm", "commercial", "farm"],
        },
        geometry=[
            box(77.590, 12.970, 77.595, 12.975),
            box(77.600, 12.970, 77.610, 12.980),
            Polygon([(77.620, 12.970), (77.630, 12.970), (77.625, 12.980)]),
            box(77.640, 12.970, 77.660, 12.990),
        ],
        crs="EPSG:4326",
    )
    path = OUT / "parcels.zip"
    with tempfile.TemporaryDirectory() as tmp:
        shp = Path(tmp) / "parcels.shp"
        parcels.to_file(shp)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for part in sorted(Path(tmp).iterdir()):
                archive.write(part, part.name)
    return path


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    print("wrote", make_kml())
    print("wrote", make_shapefile_zip())

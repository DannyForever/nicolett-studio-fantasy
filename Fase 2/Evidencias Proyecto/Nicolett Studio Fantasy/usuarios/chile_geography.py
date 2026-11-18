import json
from pathlib import Path


_DATA_PATH = Path(__file__).parent / 'data' / 'chile_dpa.json'
with _DATA_PATH.open(encoding='utf-8') as data_file:
    CHILE_DPA = json.load(data_file)

REGION_ORDER = [
    'Región de Arica y Parinacota',
    'Región de Tarapacá',
    'Región de Antofagasta',
    'Región de Atacama',
    'Región de Coquimbo',
    'Región de Valparaíso',
    'Región Metropolitana de Santiago',
    "Región de O'Higgins",
    'Región del Maule',
    'Región de Ñuble',
    'Región del Biobío',
    'Región de La Araucanía',
    'Región de Los Ríos',
    'Región de Los Lagos',
    'Región de Aysén',
    'Región de Magallanes',
]

REGIONES = {
    nombre: CHILE_DPA[nombre]['provincias']
    for nombre in REGION_ORDER
}

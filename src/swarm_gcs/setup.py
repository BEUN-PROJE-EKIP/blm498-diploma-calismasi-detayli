from setuptools import find_packages, setup

package_name = 'swarm_gcs'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Proje ekibi',
    maintainer_email='takim@example.com',
    description="Sürü yazılımının yer istasyonu paketi (görev koordinatörü, izleme, komut arayüzü iskeleti, kare sonucu alıcısı).",
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'gorev_koordinatoru = swarm_gcs.gorev_koordinatoru:main',
            'komut_gonder = swarm_gcs.komut_gonder:main',
        ],
    },
)

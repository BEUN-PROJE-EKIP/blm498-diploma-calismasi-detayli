from setuptools import find_packages, setup

package_name = 'swarm_vehicle'

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
    description="Sürü yazılımının araç süreci paketi (px4_adapter, rota üretimi).",
    license='Apache-2.0',
)

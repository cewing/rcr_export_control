from setuptools import setup, find_packages
import os

version = '1.0'

long_description = (
    open('README.txt').read()
    + '\n' +
    'Contributors\n'
    '============\n'
    + '\n' +
    open('CONTRIBUTORS.txt').read()
    + '\n' +
    open('CHANGES.txt').read()
    + '\n')

setup(name='rcr_export_control',
      version=version,
      description="Article export control script for Radiology Case Reports",
      long_description=long_description,
      # Get more strings from
      # http://pypi.python.org/pypi?%3Aaction=list_classifiers
      classifiers=[
        "Programming Language :: Python",
        ],
      keywords='OJS PKP PHP Python',
      author='Cris Ewing',
      author_email='cris@crisewing.com',
      url='https://github.com/cewing/rcr_export_control',
      license='gpl',
      packages=find_packages('src'),
      package_dir={'': 'src'},
      include_package_data=True,
      zip_safe=False,
      install_requires=[
          'setuptools',
          # -*- Extra requirements: -*-
          'argparse',
      ],
      entry_points="""
      # -*- Entry points: -*-
      [console_scripts]
      rcrexport  = rcr_export_control:main
      """,
      )

#!/usr/bin/env python

"""
@file setup.py
@author Paul Hubbard
@date 4/2/10
@brief setup file for OOI LCA architecture prototype project.
"""

setupdict = {
    'name' : 'lcaarch',
    'version' : '0.0.1',
    'description' : 'OOI LCA architecture prototype',
    'url': 'http://www.oceanobservatories.org/spaces/display/CIDev/',
    'download_url' : 'http://ooici.net/packages',
    'license' : 'Apache 2.0',
    'author' : 'Michael Meisinger',
    'author_email' : 'mmeisinger@ucsd.edu',
    'keywords': ['ooci','lcar1'],
    'classifiers' : [
    'Development Status :: 3 - Alpha',
    'Environment :: Console',
    'Intended Audience :: Developers',
    'License :: OSI Approved :: Apache Software License',
    'Operating System :: OS Independent',
    'Programming Language :: Python',
    'Topic :: Scientific/Engineering'],
}

try:
    from setuptools import setup, find_packages
    setupdict['packages'] = find_packages()
    setupdict['test_suite'] = 'lcaarch.test'
    setupdict['install_requires'] = ['Twisted', 'pycassa']
    setupdict['include_package_data'] = True
    setup(**setupdict)

except ImportError:
    from distutils.core import setup
    setupdict['packages'] = ['lcaarch']
    setup(**setupdict)

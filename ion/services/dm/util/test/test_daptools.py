#!/usr/bin/env python

"""
@file ion/services/dm/test/test_daptools.py
@author David Stuebe
@date 7/30/2010
"""

import logging
logging = logging.getLogger(__name__)

from twisted.trial import unittest
from ion.test.iontest import IonTestCase
from twisted.internet import defer

from ion.data.test.test_dataobject import ResponseServiceClient
from ion.services.dm.util import dap_tools
import os

from ion.core import ioninit
CONF = ioninit.config(__name__)

from ion.data.test import test_dataobject

import pydap
import numpy

class DapToolsBaseTest(IonTestCase):
    """
    Test the message read and write for a DAP data Object.
    """
    fname ='../ion/services/dm/util/test/test_files/grid_surf_el.nc'
    def setUp(self):
        # Load the dataset from an nc file
        self.ds1 = dap_tools.read_netcdf_from_file(self.fname)
        # Convert to a message 
        self.msg1 = dap_tools.ds2dap_msg(self.ds1)
        # Convert back to a dataset
        self.ds2 = dap_tools.dap_msg2ds(self.msg1)
        # Convert back to a message
        self.msg2 = dap_tools.ds2dap_msg(self.ds2)
        # Convert back to a dataste
        self.ds3 = dap_tools.dap_msg2ds(self.msg2)

    # Compaire the attributes, variables and variable attributes of the first two
    def test_global_atts_ds1_ds2(self):
        self._test_global_atts(self.ds1,self.ds2)
    def test_variables_ds1_ds2(self):
        self._test_variables(self.ds1,self.ds2)
    def test_variables_ds1_ds2(self):
        self._test_variable_atts(self.ds1,self.ds2)
        
    # Compaire the attributes, variables and variable attributes of the second two
    def test_global_atts_ds2_ds3(self):
        self._test_global_atts(self.ds2,self.ds3)
    def test_variables_ds2_ds3(self):
        self._test_variables(self.ds2,self.ds3)
    def test_variables_ds2_ds3(self):
        self._test_variable_atts(self.ds2,self.ds3)
        
    # Make sure we can send the msg object as a message!
    @defer.inlineCallbacks
    def test_send_dap_msg(self):
        yield self._start_container()
        services = [
            {'name':'responder','module':'ion.data.test.test_dataobject','class':'ResponseService'},
        ]

        sup = yield self._spawn_processes(services)

        rsc = ResponseServiceClient(sup)
        
        # Simple Send and Check value:
        response = yield rsc.send_data_object(self.msg1)
        self.assertEqual(self.msg1, response)
        yield self._stop_container()
    
    # Define all the helper methods
    def _test_global_atts(self, ds1, ds2):    
        # Test for equality of the attributes
        for key, value in ds1.attributes.items():
            
            logging.debug('Global Attribute: %s, types %s, %s' % (key, type(value), type(ds2.attributes[key])) ) 
            
            if isinstance(value,numpy.ndarray):
                barray = value == ds2.attributes[key]
                self.assert_(barray.all(),'Global array type attribute is not equal')
            else:
                self.assertEqual(value, ds2.attributes[key])

    def _test_variables(self,ds1,ds2):
        # Test for equality of the variables
        for key,value in ds1.items():

            logging.debug('Variable: %s, types %s, %s' % (key, type(value), type(ds2[key])) )           
            
            if isinstance(value, pydap.model.BaseType):
                barray =  value.data == ds2[key].data
                self.assert_(barray.all(), 'Variable %s array content is not equal!' % key)

            elif isinstance(value, pydap.model.GridType):
                
                #if key == 'atmp':
                #    print value.array.data
                #    print ds2[key].array.data[:]
                barray =  value.array.data == ds2[key].array.data
                self.assert_(barray.all(),'Variable %s array content is not equal!' % key)
            else:
                # Structure comparison not implemented yet!
                self.assertEqual(False,ds2[key],'Not set up to handle structures yet')

    def _test_variable_atts(self,ds1,ds2):  
        # Test for equality of the variables
        for key,value in ds1.items():

            logging.debug('Variable: %s, types %s, %s' % (key, type(value), type(ds2[key])) )           
            
            for attkey, attvalue in ds1[key].attributes.items():
                
                    logging.debug('Variable Att: %s, types %s, %s' % (attkey, type(attvalue), type(ds2[key].attributes[attkey])) )

                    if isinstance(attvalue,(numpy.ndarray, list)):
                        barray = attvalue == ds2[key].attributes[attkey]
                        if hasattr(barray,'all'):
                            barray = barray.all()
                        self.assert_(barray,'Variable array attribute are not equal')
                    elif isinstance(attvalue, (str,bool)):
                        self.assertEqual(attvalue, ds2[key].attributes[attkey])

                    else:
                        self.assertAlmostEqual(attvalue, ds2[key].attributes[attkey])
                

class DapToolsTest_GridWaterTemp(DapToolsBaseTest):
    fname ='../ion/services/dm/util/test/test_files/grid_water_temp.nc'

class DapToolsTest_GridWaterV(DapToolsBaseTest):
    fname ='../ion/services/dm/util/test/test_files/grid_water_v.nc'

class DapToolsTest_StationAtmp(DapToolsBaseTest):
    fname ='../ion/services/dm/util/test/test_files/station_atmp.nc'

class DapToolsTest_StationBaro(DapToolsBaseTest):
    fname ='../ion/services/dm/util/test/test_files/station_baro.nc'

class DapToolsTest_StationWdir(DapToolsBaseTest):
    fname ='../ion/services/dm/util/test/test_files/station_wdir.nc'


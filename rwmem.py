from migen      import *
from migen.fhdl import verilog
from migen.fhdl.verilog  import convert

from random     import randrange
from itertools import repeat

import sys
import argparse


#------------------------------------------------------------------------------
# Logic
#------------------------------------------------------------------------------

"""

Slave contains a memory and some control ports Interface is defined as follows:

-   m2s_we is a write enable signal, when asserted the operation is considered a write
-   m2s_data is the data that the MASTER wants to write into memory. It can be ignored
during a read operation
-   m2s_addr is the address of the transaction
-   s2m_ack is an acknowledge that for a write operation is sent back to the MASTER
one clock cycle after the request has been received
-   s2m_data is the data that the MEM returns to the MASTER after a read request.
s2m_ack indicates when s2m_data is valid
-   s2m_error optional error signal :
    - set to 1 if addr is set to value larger than the memory size
"""
class Mem(Module):
    def __init__(self,slave=None, data_width= 8, mem_size=10, init =None):

        #############
        # IOS
        #############
        # Inputs
        self.m2s_addr   = Signal(data_width)
        self.m2s_data   = Signal(data_width)
        self.m2s_we     = Signal()
        
        # Outputs
        self.s2m_data   = Signal(data_width)
        self.s2m_ack    = Signal()
        self.s2m_error  = Signal()

        # Easier to fetch in Verilog
        self.ios = { self.m2s_we,  
                     self.m2s_data,
                     self.m2s_addr,
                     self.s2m_ack  ,
                     self.s2m_data ,
                     self.s2m_error } 

        #Memory Initialization
        mem_inst            = Memory(data_width, mem_size, init=init)
        mem_ports           = mem_inst.get_port(write_capable=True)
        self.specials       += mem_ports, mem_inst

        #######################################
        # Inputs && Outputs assignment to Mem
        #######################################

        self.comb +=  [
            mem_ports.we.eq(self.m2s_we),
            mem_ports.dat_w.eq(self.m2s_data),
            mem_ports.adr.eq(self.m2s_addr),
            self.s2m_data.eq(mem_ports.dat_r)
        ]


        ################
        #   Ack Logic
        ################

        # Store last data_r to be used to create ACK when there is no WE

        #Internal Signals
        ack_we  = Signal()

        # Write ack declaration
        # Ack should be 1 cycle after the we
        self.sync +=  [
            ack_we.eq(mem_ports.we)
        ]

        # Read ack declaration  
        # Internal Signals    
        ack_re     = Signal()

        addr_new   = Signal(data_width)
        ack_re_reg = Signal()
        
        # Ack should be 1 cycle after the addr change, if we hadn't change
        self.sync +=  [
            addr_new.eq(self.m2s_addr),
            ack_re_reg.eq(ack_re)
        ]
        self.comb +=  [
            If( (addr_new == self.m2s_addr) & (mem_ports.we == 0) ,
                ack_re.eq(1)
            ).Else(
                ack_re.eq(0) 
            ),

        ]

        #Output Ack
        # It should be zero on error
        self.comb +=  [   self.s2m_ack.eq( (ack_re  | ack_we) & ~self.s2m_error) ]

        ################
        #  Error Logic
        ################

        self.comb += [
            If( self.m2s_addr >= mem_size,
                self.s2m_error.eq(1)
            ).Else(
                self.s2m_error.eq(0)
            )
        ]


"""

Master is only an interface with usefull functions to write and to read
from the slave memory

"""
class Master(Module):
    def __init__(self, slave=None, mem_size=10, data_width=8, init=None):

        #Add Master on top of Memory
        if slave is None:
            slave = Mem(mem_size=mem_size, data_width=data_width, init=init)
        self.submodules.slave = slave

        # M2S (Output)
        self.m2s_we    = Signal()
        self.m2s_data  = Signal(mem_size)
        self.m2s_addr  = Signal(mem_size)
        
        # S2M (Input)
        self.s2m_ack   = Signal()
        self.s2m_data  = Signal(mem_size)
        self.s2m_ack   = Signal()
        self.s2m_error = Signal()

        # Change if needed
        self.ios = set()

        self.comb += [
            slave.m2s_we    .eq(self.m2s_we   ),
            slave.m2s_data  .eq(self.m2s_data ),
            slave.m2s_addr  .eq(self.m2s_addr ),
            self.s2m_ack   .eq(slave.s2m_ack  ),
            self.s2m_data  .eq(slave.s2m_data ),
            self.s2m_ack   .eq(slave.s2m_ack  ),
            self.s2m_error .eq(slave.s2m_error)
        ]

        

    ## UTIL FUNCTS
    def write(self, adr, dat):
        timeout = 0
        yield self.m2s_addr.eq(adr)
        yield self.m2s_data.eq(dat)
        yield self.m2s_we.eq(1)
        yield
        yield self.m2s_we.eq(0)
        while not ((yield self.s2m_ack) or (yield self.s2m_error)):
            timeout += 1
            assert timeout < 20
            yield
        value = yield self.s2m_data
        error = yield self.s2m_error 
        return value, error


    def read(self, adr):
        timeout = 0
        yield self.m2s_addr.eq(adr)
        yield
        while not ((yield self.s2m_ack) or (yield self.s2m_error)):
            timeout += 1
            assert timeout < 20
            yield
        value = yield self.s2m_data
        error = yield self.s2m_error 
        return value, error

#------------------------------------------------------------------------------
# Tests
#------------------------------------------------------------------------------

#Useful Tests
def test_write_range_width(dut, mem_size=10, data_width=8, regress_times=20,init_mem_values=None):

    # Write
    counter = regress_times
    if counter is None:
        counter = mem_size

    value_written = {}
    for i in range(counter):
        to_write = randrange(2**data_width)
        
        addr     = randrange(mem_size) 
        if regress_times is None:
            addr = i

        value_written.update({addr:to_write})
        wrote_value = yield from dut.write(addr,to_write)
        print("Wrote value:" , wrote_value, " on: ", addr, "Expecting: ", str(to_write)) 
        assert wrote_value == (to_write,0)

    return value_written

"""

 This test can also be used to test initialization values
 
"""
def test_read_range_width(dut,value_written=None, mem_size=10, data_width=8, regress_times=None, init_mem_values=None):

    #Check if init values exist
    if init_mem_values is None:
        init_mem_values = [0] * mem_size

    #Check if init values list contains appropriate len
    # if not append zeros and read
    if len(init_mem_values) < mem_size:
        print(len(init_mem_values))
        init_mem_values = init_mem_values + list(repeat(0,mem_size))

    # Only enters here if testing initialization values (use -l option)
    if value_written is None:
        print("Testing Initialization values")
        value_written = {}
        for addr in range(mem_size):
            value_written.update({addr:init_mem_values[addr]})


    for addr, value in value_written.items():
        ret = yield from dut.read(addr)
        print("Reading from: ",addr, " :" , ret, "Expected: ", value)
        assert ret == (value,0)
        yield

# Full test
def test_write_read_range_width(dut, mem_size=10, data_width=8, regress_times=None,init_mem_values=None):
    # Write 
    value_written = yield from test_write_range_width( dut, mem_size, data_width, regress_times, init_mem_values)

    # Read
    yield from test_read_range_width(dut,value_written, mem_size)


def test_write_read_range_max_error(dut, mem_size=10, data_width=8, regress_times=None,init_mem_values=None):
    max = mem_size **2 
    rand_location = randrange(mem_size+1, max)
    print("Reading from: ", rand_location)
    value = yield from dut.read(rand_location)
    print("Read:" , value)
    assert value[1] == 1


#------------------------------------------------------------------------------
# Builder Class
#------------------------------------------------------------------------------

class Builder:

    def __init__(self, config):
        self.return_code        = 0
        self.dut                = config['dut_name']
        self.mem_size           = config["memory_size"] 
        self.data_width         = config["data_width"] 
        self.regression_list    = config["regression_list"].split(',')
        self.create_vcd         = config["create_vcd"]
        self.regression_counter = config["regression_counter"]

        self.memory             = None
        if config["memory_name"] is not None:
            self.memory         = eval(config["memory_name"])()
        
        self.init_mem_values = None
        if config["init_mem_values"] is not None:
            self.init_mem_values    = list(map(int, config["init_mem_values"].split(',')))


    def run(self):
        ## Run Options
        if config["run_regression"]:
            self.return_code = self.test_regression()
        if config['print_verilog']:
            print("Printing Verilog to STDIN")
            print(self.print_verilog())
        if config['write_verilog']:
            print("Writting Verilog: {}".format(config['write_verilog']))
            self.print_verilog().write(config['write_verilog'])
        
        return self.return_code

    def print_verilog(self):
        dut = eval(self.dut)(self.memory,self.mem_size,self.data_width,self.init_mem_values)
        self.return_code = 1
        return convert(dut, dut.ios)

    def test_regression(self):
        for test in self.regression_list:
            print("Testing {} using {}".format(self.dut, test))

            ## Create another DUT because: AssertionError -  assert(not self.get_fragment_called)
            dut = eval(self.dut)(self.memory,self.mem_size,self.data_width,self.init_mem_values)
            
            vcd_name = None
            if self.create_vcd:
                vcd_name = self.dut+"_"+test+".vcd"
        
            run_simulation( dut, 
                            eval(test)(dut, mem_size=self.mem_size, data_width=self.data_width, regress_times=self.regression_counter, init_mem_values=self.init_mem_values),
                            vcd_name=vcd_name
                            )
        return 1

####
# Defaults
#####
default_create_vcd              = False
default_verilog_print           = False
default_write_verilog           = False
default_run_regression          = False
default_top_module              = "Master"
default_mem_module              = None 
default_regression_list         = "test_read_range_width,test_write_range_width,test_write_read_range_width,test_write_read_range_max_error"
default_mem_size                = 10
default_data_width              = 8
default_regression_counter      = None
default_init_values             = None
#
# Arg passer
#
class ArgumentParser_Builder():
    def __init__(self, parser):
        parser.add_argument('-p', '--print_verilog',  action='count',
            help='Print the verilog description. Default: {0}'.format(default_verilog_print),
            default=default_verilog_print)
        parser.add_argument('-v', '--write_verilog',  type=str,
            help='Print the verilog description. Default: {0}'.format(default_write_verilog),
            default=default_write_verilog)
        parser.add_argument('-r', '--run_regression',  action='count',
            help='Run a default regression suite. Default: {0}'.format(default_run_regression),
            default=default_run_regression)
        parser.add_argument('-w', '--create_vcd',  action='count',
            help='Create VCD. Default: {0}'.format(default_create_vcd),
            default=default_create_vcd)
        parser.add_argument('-d', '--dut_name', type=str,
            help='Change the name of the DUT (Mem can only be used to write the Verilog). Default: {0}'.format(default_top_module),
            default=default_top_module)
        parser.add_argument('-m', '--memory_name', type=str,
            help='Change the name of the Memory. Default: {0}'.format(default_mem_module),
            default=default_mem_module)
        parser.add_argument('-s', '--memory_size', type=int,
            help='Set the memory size. Default: {0}'.format(default_mem_size),
            default=default_mem_size)
        parser.add_argument('-a', '--data_width', type=int,
            help='Change the Interface data_width. Default: {0}'.format(default_data_width),
            default=default_data_width)
        parser.add_argument('-l', '--regression_list', type=str,
            help='Regression suite tests seperated by ",". Default: {0}'.format(default_regression_list),
            default=default_regression_list)
        parser.add_argument('-c', '--regression_counter', type=int,
            help='Number of times a write request is done". Default: Max Width of memory'.format(default_regression_counter),
            default=default_regression_counter)
        parser.add_argument('-i', '--init_mem_values', type=str,
            help='Initialize the memory. Default: {0}'.format(default_init_values),
            default=default_init_values)


# ------------------------------------------------------------------------------
# If Builder class is executed as script
# ------------------------------------------------------------------------------
if __name__ == '__main__':
    """ The class is executed as script """
    print("Starting")
    sys.dont_write_bytecode = True
    
 # ------------------------------------------------------------------------------
 # Argument parser
 # ------------------------------------------------------------------------------
    parser = argparse.ArgumentParser(
    description='This script is used to create a read/Write memory with a simple Master')
    ArgumentParser_Builder(parser)

 # ------------------------------------------------------------------------------
 # Argument Check
 # ------------------------------------------------------------------------------
    config = vars(parser.parse_args())

 # ------------------------------------------------------------------------------
 # Run script
 # ------------------------------------------------------------------------------

    builder = Builder(config)
    return_code = builder.run()

    if return_code != 1:
        parser.print_help()

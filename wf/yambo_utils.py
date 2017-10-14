import sys
import copy
from aiida.backends.utils import load_dbenv, is_dbenv_loaded

if not is_dbenv_loaded():
    load_dbenv()

from aiida.common.exceptions import InputValidationError,ValidationError, WorkflowInputValidationError
from aiida.orm import load_node
from aiida.orm.data.upf import get_pseudos_from_structure
from collections import defaultdict
from aiida.orm.utils import DataFactory
from aiida.orm.code import Code
from aiida.orm.data.structure import StructureData
from aiida.orm.calculation.job.yambo  import YamboCalculation
from aiida.orm.calculation.job.quantumespresso.pw import PwCalculation

ParameterData = DataFactory("parameter")

def generate_yambo_input_params(precodename,yambocodename, parent_folder, parameters,  calculation_set, settings):
    inputs = YamboCalculation.process().get_inputs_template()
    inputs.preprocessing_code = Code.get_from_string(precodename.value)
    inputs.code = Code.get_from_string(yambocodename.value)
    calculation_set = calculation_set.get_dict()
    resource = calculation_set.pop('resources', {})
    if resource:
        inputs._options.resources =  resource 
    inputs._options.max_wallclock_seconds =  calculation_set.pop('max_wallclock_seconds', 86400) 
    max_memory_kb = calculation_set.pop('max_memory_kb',None)
    if max_memory_kb:
        inputs._options.max_memory_kb = max_memory_kb
    queue_name = calculation_set.pop('queue_name',None)
    if queue_name:
        inputs._options.queue_name = queue_name 
    custom_scheduler_commands = calculation_set.pop('custom_scheduler_commands',None)
    if custom_scheduler_commands:
        inputs._options.custom_scheduler_commands = custom_scheduler_commands
    environment_variables = calculation_set.pop("environment_variables",None)
    if environment_variables:
        inputs._options.environment_variables = environment_variables
    label = calculation_set.pop('label',None)
    if label:
        inputs._label = label 
    inputs.parent_folder = parent_folder
    inputs.settings =  settings 
    # Get defaults:
    edit_parameters = parameters.get_dict()
    try:
        calc = parent_folder.get_inputs_dict()['remote_folder'].inp.parent_calc_folder.get_inputs_dict()\
               ['remote_folder'].inp.parent_calc_folder.get_inputs_dict()['remote_folder']
    except AttributeError:
        calc = None
    is_pw = False
    if isinstance(calc,PwCalculation):
        is_pw = True
        nelec = calc.out.output_parameters.get_dict()['number_of_electrons']
        bndsrnxp = gbndrnge = nelec 
        ngsblxpp = int(calc.out.output_parameters.get_dict()['wfc_cutoff']* 0.073498645/4 * 0.4)   # ev to ry then 1/4 
        nkpts = calc.out.output_parameters.get_dict()['number_of_k_points']
        if 'BndsRnXp' not in edit_parameters.keys():
             edit_parameters['BndsRnXp'] = (1.0,bndsrnxp*2)
        if 'GbndRnge' not in edit_parameters.keys():
             edit_parameters['GbndRnge'] = (1.0, gbndrnge*2) 
        if 'NGsBlkXp' not in edit_parameters.keys():
             edit_parameters['NGsBlkXp'] = ngsblxpp
             edit_parameters['NGsBlkXp_units'] =  'eV'
        if 'QPkrange' not in edit_parameters.keys():
             edit_parameters['QPkrange'] = [(1,1,int(nelec/2), int(nelec/2)+1 )]
        if 'SE_CPU' not in  edit_parameters.keys():
            edit_parameters['SE_CPU'] ="1 8 16" 
            edit_parameters['SE_ROLEs']= "q qp b"
        if 'X_all_q_CPU' not in  edit_parameters.keys():
            edit_parameters['X_all_q_CPU']= "1 1 16 8"
            edit_parameters['X_all_q_ROLEs'] ="q k c v"
    
    inputs.parameters = ParameterData(dict=edit_parameters) 
    return  inputs

def get_pseudo(structure, pseudo_family):
    kind_pseudo_dict = get_pseudos_from_structure(structure, pseudo_family)
    pseudo_dict = {}
    pseudo_species = defaultdict(list)
    for kindname, pseudo in kind_pseudo_dict.iteritems():
        pseudo_dict[pseudo.pk] = pseudo
        pseudo_species[pseudo.pk].append(kindname)
    pseudos = {}
    for pseudo_pk in pseudo_dict:
        pseudo = pseudo_dict[pseudo_pk]
        kinds = pseudo_species[pseudo_pk]
        for kind in kinds:
            pseudos[kind] = pseudo
    return pseudos


def generate_pw_input_params(structure, codename, pseudo_family,parameters, calculation_set, kpoints,gamma,settings,parent_folder):
    """
    inputs_template: {'code': None, 'vdw_table': None, 'parameters': None, 
                      '_options': DictSchemaInputs({'resources': DictSchemaInputs({})}), 
                      'kpoints': None, 'settings': None, 'pseudo': None, 
                      'parent_folder': None, 'structure': None}
    """
    inputs = PwCalculation.process().get_inputs_template()
    inputs.structure = structure
    inputs.code = Code.get_from_string(codename.value)
    calculation_set = calculation_set.get_dict() 
    resource = calculation_set.pop('resources', {})
    if resource:
        inputs._options.resources =  resource
    inputs._options.max_wallclock_seconds =  calculation_set.pop('max_wallclock_seconds', 86400) 
    max_memory_kb = calculation_set.pop('max_memory_kb',None)
    if max_memory_kb:
        inputs._options.max_memory_kb = max_memory_kb
    queue_name = calculation_set.pop('queue_name',None)
    if queue_name:
        inputs._options.queue_name = queue_name           
    custom_scheduler_commands = calculation_set.pop('custom_scheduler_commands',None)
    if custom_scheduler_commands:
        inputs._options.custom_scheduler_commands = custom_scheduler_commands
    environment_variables = calculation_set.pop("environment_variables",None)
    if environment_variables:
        inputs._options.environment_variables = environment_variables
    label = calculation_set.pop('label',None)
    if label :
        inputs._label = label
    if parent_folder:
        inputs.parent_folder = parent_folder
    inputs.kpoints=kpoints
    inputs.parameters = parameters  
    inputs.pseudo = get_pseudo(structure, str(pseudo_family))
    inputs.settings  = settings
    #if gamma:
    #    inputs.settings = ParameterData(dict={'gamma_only':True})
    return  inputs


def reduce_parallelism(typ, roles,  values,calc_set):
    """
                        X_all_q_CPU = params.pop('X_all_q_CPU','')
                        X_all_q_ROLEs =  params.pop('X_all_q_ROLEs','')
                        SE_CPU = params.pop('SE_CPU','')
                        SE_ROLEs = params.pop('SE_ROLEs','')
                        calculation_set_yambo ={'resources':  {"num_machines": 8,"num_mpiprocs_per_machine": 32}, 'max_wallclock_seconds': 200,
                             'max_memory_kb': 1*92*1000000 ,  'custom_scheduler_commands': u"#PBS -A  Pra14_3622" ,
                             '  environment_variables': {"OMP_NUM_THREADS": "2" }  
                             }
    """
    calculation_set = copy.deepcopy(calc_set)
    # the latter needs to be reduced, we can either increase the former or leave it untouched.
    # lets reduce it by  50% if its >=2, else increase num_machines, holding it constant at 1
    num_machines = calculation_set['resources']['num_machines']    
    num_mpiprocs_per_machine = calculation_set['resources']['num_mpiprocs_per_machine']
    omp_threads=1
    if 'environment_variables' in calculation_set.keys():
        omp_threads = calculation_set['environment_variables'].pop('OMP_NUM_THREADS',1)
    num_mpiprocs_per_machine=int(num_mpiprocs_per_machine/2)
    omp_threads= int(omp_threads)*2 
    if num_mpiprocs_per_machine < 1:
        num_mpiprocs_per_machine = 1 
        num_machines = num_machines * 2
    calculation_set['environment_variables']['OMP_NUM_THREADS'] = str(omp_threads)
    calculation_set['environment_variables']['NUM_CORES_PER_MPIPROC'] = str(omp_threads)
    if isinstance(values,list):
        values = values[0]
    if isinstance(roles,list):
        roles = roles[0]
    # adjust the X_all_q_CPU and SE_CPU
    mpi_task = num_mpiprocs_per_machine*num_machines 
    if typ == 'X_all_q_CPU':
        #X_all_q_CPU = "1 1 96 32"
        #X_all_q_ROLEs = "q k c v"
        X_para = [ int(it) for it in values.strip().split(' ') if it ]
        try:
            c_index = roles.split(' ').index("c")
            v_index = roles.split(' ').index("v")
            c = X_para[c_index] or 1
            v = X_para[v_index] or 1
        except ValueError:
            c_index = v_index = 0
            c = 1
            v = 1
        except IndexError:
            c_index = v_index = 0
            c = 1
            v = 1
        if c_index and v_index:
            pass
        if num_mpiprocs_per_machine < calculation_set['resources']['num_mpiprocs_per_machine'] and v >1:
            v = v/2 
        if num_mpiprocs_per_machine < calculation_set['resources']['num_mpiprocs_per_machine'] and v == 1:
            c = c/2 
        if num_machines > calculation_set['resources']['num_machines']: 
            c = c*2 
        if c_index and v_index:
            X_para[c_index] = c  
            X_para[v_index] = v
        X_string = " ".join([str(it) for it in X_para])
        calculation_set['resources']['num_machines'] = num_machines
        calculation_set['resources']['num_mpiprocs_per_machine'] = num_mpiprocs_per_machine
        if c_index and v_index:
            pass
        print("X_all_q_CPU", X_string, " :from: ", X_para)
        return X_string , calculation_set
            
    if typ == 'SE_CPU':
        #SE_ROLEs = "q qp b"
        #SE_CPU = "1 32 96"
        SE_para  = [ int(it) for it in values.strip().split(' ') if it ]
        try:
            qp_index = roles.split(' ').index("qp")
            b_index = roles.split(' ').index("b")
            qp = SE_para[qp_index] or  1
            b  = SE_para[b_index] or 1  
        except ValueError:
            qp_index = b_index = 0
            qp =1
            b  =1  
        except IndexError:
            qp_index = b_index = 0
            qp =1
            b  =1  
        if qp_index and b_index: 
            pass
        if num_mpiprocs_per_machine < calculation_set['resources']['num_mpiprocs_per_machine'] and qp >1:
             qp = qp/2 
        if num_mpiprocs_per_machine < calculation_set['resources']['num_mpiprocs_per_machine'] and qp == 1:
            qp = qp/2 
        if num_machines > calculation_set['resources']['num_machines']: 
            b = b*2 
        if qp_index and b_index: 
            SE_para[qp_index] = qp  
            SE_para[b_index] = b
        SE_string = " ".join([str(it) for it in SE_para])
        print("SE_string", SE_string, " : from:", SE_para )
        calculation_set['resources']['num_machines'] = num_machines
        calculation_set['resources']['num_mpiprocs_per_machine'] = num_mpiprocs_per_machine
        if qp_index and b_index: 
            pass
        return SE_string, calculation_set
   

default_step_size = {
               'PPAPntXp': .2,   
               'NGsBlkXp': .1,   
               'BSENGBlk': .1,  
               'BSENGexx': .2,
               'BndsRnXp': .2, 
               'GbndRnge': .2,
               'BSEBands': 2, # 
                }

def update_parameter_field( field, starting_point, update_delta):
    if update_delta < 2:
       update_delta = 2 
    if field in ['PPAPntXp','NGsBlkXp','BSENGBlk','BSENGexx']: # single numbers
        new_field_value =  starting_point  + update_delta 
        return new_field_value
    elif field == 'BndsRnXp':
        new_field_value =  starting_point  + update_delta 
        #new_field_value =  starting_point[-1]  + update_delta 
        #return (starting_point[0], new_field_value)
        return (1, new_field_value)
    elif field == 'GbndRnge':
        new_field_value =  starting_point   + update_delta 
        #new_field_value =  starting_point[-1]  + update_delta 
        #return (starting_point[0], new_field_value)
        return (1, new_field_value)
    elif field == 'BSEBands':  # Will be useful when we support BSE calculations
        hi =  starting_point +   update_delta
        low  =  starting_point  -  update_delta
        return ( low, hi )
    #elif field == 'QPkrange':
    #    hi = starting_point[1] + update_delta
    #    return [(starting_point[0], hi, starting_point[-2], starting_point[-1] )]
    else:
        raise WorkflowInputValidationError("convergences the field {} are not supported".format(field))


def set_default_qp_param(parameter=None):
    """
    """
    if not parameter:
       parameter = ParameterData(dict={})
    edit_param = parameter.get_dict()
    if 'ppa' not in edit_param.keys():
        edit_param['ppa'] = True
    if 'gw0' not in edit_param.keys():
        edit_param['gw0'] = True
    if 'HF_and_locXC' not in edit_param.keys():
        edit_param['HF_and_locXC'] = True
    if 'em1d' not in edit_param.keys():
        edit_param['em1d'] = True
    if 'DysSolver' not in edit_param.keys():
        edit_param['DysSolver'] = "n"
    if 'Chimod' not in edit_param.keys():
        edit_param['Chimod'] = "Hartree"
    if 'LongDrXp' not in edit_param.keys():
        edit_param['LongDrXp'] = (1.000000,0.000000, 0.000000)
    if 'PPAPntXp' not in edit_param.keys():
        edit_param['PPAPntXp'] =  10
        edit_param['PPAPntXp_units'] =  'eV'
    if 'SE_CPU' not in  edit_param.keys():
        edit_param['SE_CPU'] ="1 8 16" 
        edit_param['SE_ROLEs']= "q qp b"
    if 'X_all_q_CPU' not in  edit_param.keys():
        edit_param['X_all_q_CPU']= "1 1 16 8"
        edit_param['X_all_q_ROLEs'] ="q k c v"
    return ParameterData(dict=edit_param)


def set_default_pw_param():
    pw_parameters =  {
          'CONTROL': {
              'calculation': 'scf',
              'restart_mode': 'from_scratch',
              'wf_collect': True,
              'tprnfor': True,
              'etot_conv_thr': 0.00001,
              'forc_conv_thr': 0.0001,
              'verbosity' :'high',
              },
          'SYSTEM': {
              'ecutwfc': 45.,
              'occupations':'smearing',
              'degauss': 0.001,
              'starting_magnetization(1)' : 0.0,
              'smearing': 'fermi-dirac',
              },
          'ELECTRONS': {
              'conv_thr': 1.e-8,
              'electron_maxstep ': 100,
              'mixing_mode': 'plain',
              'mixing_beta' : 0.3,
              } }
    return ParameterData(dict=pw_parameters)

def default_pw_settings():
    return ParameterData(dict={})
 
def yambo_default_settings():
    return ParameterData(dict={"ADDITIONAL_RETRIEVE_LIST":[
                             'r-*','o-*','l-*','l_*','LOG/l-*_CPU_1','aiida/ndb.QP','aiida/ndb.HF_and_locXC'] })      
 
def p2y_default_settings():
    return ParameterData(dict={ "ADDITIONAL_RETRIEVE_LIST":['r-*','o-*','l-*','l_*','LOG/l-*_CPU_1'], 'INITIALISE':True})


def default_qpkrange(calc_pk, parameters):
    calc = load_node(calc_pk)
    edit_parameters = parameters.get_dict()
    if isinstance(calc,PwCalculation):
       is_pw = True
       nelec = calc.out.output_parameters.get_dict()['number_of_electrons']
       nkpts = calc.out.output_parameters.get_dict()['number_of_k_points']
       if 'QPkrange' not in edit_parameters.keys():
            edit_parameters['QPkrange'] = [(1,nkpts/2 , int(nelec*3) , int(nelec*3)+1 )]
    return ParameterData(dict=edit_parameters)

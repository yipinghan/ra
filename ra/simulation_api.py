import numpy as np
import math
from ra.rayinidir import RayInitialDirections
from ra.receivers import setup_receivers
from ra.sources import setup_sources
from ra.controlsair import AlgControls, AirProperties
from ra.room import Geometry, GeometryMat
from ra.absorption_database import load_matdata_from_mat, get_alpha_s
from ra.statistics import StatisticalMat
from ra.ray_initializer import ray_initializer
from ra.results import process_results, SRStats
import ra_cpp
# from ra.room import vert_2d, triangle_area, triangle_centroid
from ra.room import GeometryApi
from ra.rayinidir import RayInitialDirections

class Simulation():
    def __init__(self,):
        # self.controls = {} # algorithm controls
        # self.air = {} # air properties
        self.sources = []
        self.receivers = []
        # self.geometry = {}

    def set_configs(self, config):
        '''
        This function set the algortim configurations.
        Parameters:
        ----------
            config: dictionary of algoritm configurations
        '''
        self.freq = np.array(config['freq'], dtype = np.float32)
        self.Nrays = config['n_rays']
        self.ht_length = config['ht_length']
        self.Dt = config['dt']
        self.allow_scattering = config['allow_scattering']
        self.transition_order = config['transition_order']
        self.rec_radius_init = config['rec_radius_init']
        self.alow_growth = config['allow_growth']
        self.rec_radius_final = config['rec_radius_final']

    def set_air(self, air_properties):
        '''
        This function set the air properties.
        Parameters:
        ----------
            air_properties: dictionary of air properties:
            - temperature is Temperature in [C]
            - h_r is relative humidity in %
            - p_atm is atmospheric pressure in Pa
        The function will calculate the sound speed, air density,
        and the air absorption coefficient m in [1/m]
        '''
        self.temperature = air_properties['Temperature']
        self.hr = air_properties['hr']
        self.p_atm = air_properties['p_atm']
        ############# Calculate sound speed and air density #############
        temp_kelvin = self.temperature + 273.16 # temperature in [K]
        R = 287.031                 # gas constant
        rvp = 461.521               # gas constant for water vapor
        # pvp from Pierce Acoustics 1955 - pag. 555
        pvp = 0.0658 * temp_kelvin**3 - 53.7558 * temp_kelvin**2 \
            + 14703.8127 * temp_kelvin - 1345485.0465
        # Constant pressure specific heat
        cp = 4168.8 * (0.249679 - 7.55179e-5 * temp_kelvin \
            + 1.69194e-7 * temp_kelvin**2 \
            - 6.46128e-11 * temp_kelvin**3)
        cv = cp - R                 # Constant volume specific heat
        # b2 = vis * cp / kappla      # Prandtl number
        gam = cp / cv               # specific heat constant ratio
        # Air density
        self.rho0 = self.p_atm / (R * temp_kelvin) \
            - (1/R - 1/rvp) * self.hr/100 * pvp/temp_kelvin
        # Air sound speed
        self.c0 = (gam * self.p_atm/self.rho0)**0.5
        ###### Calculate air absorption #######################
        T_0 = 293.15                # Reference temperature [k]
        T_01 = 273.15               # 0 [C] in [k]
        temp_kelvin = self.temperature + 273.15 # Input temp in [k]
        patm_atm = self.p_atm / 101325 # atmosferic pressure [atm]
        F = self.freq / patm_atm         # relative frequency
        a_ps_ar = np.zeros(F.shape)
        # Saturation pressure
        psat = patm_atm * 10**(-6.8346 * (T_01/temp_kelvin)**1.261 \
            + 4.6151)
        h = patm_atm * self.hr *(psat/patm_atm)
        # Oxygen gas molecule (N2) relaxation frequency
        F_rO = 1/patm_atm * (24 + 4.04 * 10**4 * h * (0.02 + h) \
            / (0.391 + h))
        # Nytrogen gas molecule (N2) relaxation frequency
        F_rN = 1/patm_atm * (T_0/temp_kelvin)**(1/2) * \
            (9 + 280 * h *np.exp(-4.17 * ((T_0/temp_kelvin)**(1/3) - 1)) )
        # Air absorption in [dB/m]
        alpha_ps = 100 * F**2 / patm_atm * (1.84 \
            * 10**(-11) * (temp_kelvin/T_0)**(1/2) \
                + (temp_kelvin/T_0)**(-5/2) \
            * (0.01278 * np.exp(-2239.1/temp_kelvin) \
                / (F_rO + F**2 / F_rO) \
            + 0.1068*np.exp(-3352/temp_kelvin) / (F_rN + F**2 / F_rN)))
        a_ps_ar = alpha_ps * 20 / np.log(10)
        # Air absorption in [1/m]
        self.m = np.array((1/100) * a_ps_ar * patm_atm \
            / (10 * np.log10(np.exp(1))), dtype = np.float32)

    def set_geometry(self, geom_dict):
        '''
        set up the geometry as a list of planes (inside geometry), volume and total area.
        Parameters:
        -----------
            geom_dict: list of dicts with the following parameters: 'name',
            'vertices', 'normal', alpha, s.
        '''
        self.geometry = GeometryApi(geom_dict)

    def set_raydir(self,):
        self.rays_v = RayInitialDirections()
        # FIXME - here there is some deoendence on user interface
        # (will it be allowed to change the type of sound source?)
        # if so, we must increment this in the near future
        self.rays_v.random_rays(self.Nrays)

    def set_receivers(self, recs):
        '''
        set up the receivers (coord and orientation) and
        1: receivers - contains a receiver object with the properties:
            coord - the 3D position of the receiver.
            orientation - the orientation of the receiver.
            methods to point the receiver in a source direction.
        2: reccross - this object will contain all source-ray-receiver
        relative data (for the calculation of ray-receiver intersections at reflections), such as:
            time_cross - the time instants for which a receiver is crossed
            for a given sound source and for a given ray.
            rad_cross - the receiver radius at the instant a receiver is crossed
            for a given sound source and for a given ray.
            ref_order - the reflection order at the instant a receiver is crossed
            cos_cross - the crossing angle of reflection
            for a given sound source and for a given ray.
            An std::vector of reccross objects will be passed to each ray
            object, generating an std::vector of rays. These rays will be
            passed to each source object. This will generate the dependence
            source-ray-receiver
        3: reccrossdir (for the calculation of ray-receiver intersections at direct sound)
            size_of_time - to help posterior concatenation
            time_dir - direct sound time of arrival
            hits_dir - number of hits on direct sound (maybe will be discontinuated)
            cos_dir - the crossing angle of direct sound
        Parameters:
        -----------
            recs: list of receiver dictionaries

        '''
        self.receivers = [] # An array of empty receiver objects
        self.reccross = [] # An array of empty reccross data objects
        self.reccrossdir = [] # An array of empty reccrossdir data objects
        for r in recs:
            # coord = np.array(r['position'], dtype=np.float32)
            # orientation = np.array(r['orientation'], dtype=np.float32)
            # print(orientation)
            ################### cpp receiver class #################
            self.receivers.append(
                ra_cpp.Receivercpp(r['coord'], r['orientation'])) # FIXME orientation is returning zeros from c++Append the receiver object
            self.reccross.append(
                ra_cpp.RecCrosscpp([], [], [], [])) # Append the reccross object
            self.reccrossdir.append(
                ra_cpp.RecCrossDircpp(0, 0.0, 0, 0.0))

    def set_memory_init(self,):
        '''
        Initialize memory allocation from python side, so c++ can calculate
        '''
        # Estimate max reflection order
        N_max_ref = math.ceil(1.5 * self.c0 * self.ht_length * \
            (self.geometry.total_area / (4 * self.geometry.volume)))
        # Allocate according to max reflection order
        self.rays = ray_initializer(self.rays_v, N_max_ref, self.transition_order, self.reccross)

    def set_sources(self, srcs):
        '''
        Set up the sound sources
        Each sound source object has three main categories of data:
        A - sound source properties (given by user - read from parameters:
        ----------
            srcs: list of Source's dictionaries with):
                coord - the 3D position of the receiver.
                orientation - the orientation of the receiver.
                power_dB - sound power in dB (len(contrlos.freq x 1)
                eq_dB - sound power equalization in dB (len(contrlos.freq x 1)
                power_lin - sound power in Watts (len(contrlos.freq x 1)
                delay - sound source delay [s].
        B - a std::vector of rays (objects). Each ray object contains:
            1: planes_hist - the history of planes indexes found during
                the ray travell in the room (1 x N_max_ref)
            2: refpts_hist - the history of reflection points found during
                the ray travell in the room (N_max_ref x 3 - floats) 
            3: a std::vector of reccross. Each recs object will contain 
            all source-ray-receiver relative data, such as:
                time_cross - the time instants for which a receiver is
                crossed for a given sound source and for a given ray.
                rad_cross - the receiver radius at the instant a receiver
                is crossed for a given sound source and for a given ray.
                ref_order - the reflection order at the instant a receiver
                is crossed for a given sound source and for a given ray.
        This way there is a dependence source-ray-receiver
        C - a std::vector of reccrossdir (objects). Each ray object contains:
            size_of_time - to help posterior concatenation
            time_dir - direct sound time of arrival
            hits_dir - number of hits on direct sound (maybe will be discontinuated)
            cos_dir - the crossing angle of direct sound
        This way there is a dependence source-receiver for direct sound
        '''
        self.sources = [] # An array of empty souce objects
        for s in srcs:
            coord = np.array(s['coord'], dtype=np.float32)
            orientation = np.array(s['orientation'], dtype=np.float32)
            power_dB = np.array(s['power_dB'], dtype=np.float32)
            eq_dB = np.array(s['eq_dB'], dtype=np.float32)
            power_lin = (10.0**-12) * 10**((power_dB + eq_dB) / 10.0)
            delay = s['delay'] / 1000
            ################### cpp source class #################
            self.sources.append(ra_cpp.Sourcecpp(coord, orientation,
                power_dB, eq_dB, power_lin, delay, self.rays, self.reccrossdir)) # Append the source object

    def run_statistical_reverberation(self,):
        '''
        Method runs statistical theory for preliminary analysis of reverberation time.
        It disregards the specific geometry of the room, using only general attributes
        such as volume and surface areas. The sound absorption may be considered as an
        spatial average of some sort.
        '''
        self.statistical_revtime = StatisticalMat(self.geometry, self.freq, self.c0, self.m)
        # Sabine eyring and arau-puchades are the default in ODEON
        self.statistical_revtime.t60_sabine()
        self.statistical_revtime.t60_eyring()
        self.statistical_revtime.t60_araup()
        # self.statistical_revtime.t60_kutruff(gamma=0.4)
        # self.statistical_revtime.t60_fitzroy()
        # self.statistical_revtime.t60_milsette()

    def run_raytracing(self,):
        '''
        Every time we run a ray tracing calculation there are a few things that need to happen so
        we complete the calculations:
        1 - The direct sound must be computed
        2 - The ray tracing part (reflected part) is computed (This is the most burdensome part)
        Parts 1 and 2 do not need to be computed if a user chages the absorption of some material in the scene
        3 - Intensities must be computed
        4 - Reflectogram, decay and acoustical parameters are computed
        Parts 3 and 4 must be computed if a user chages the absorption of some material in the scene.
        If only the absorption is changed there can be a function to do only these steps.
        '''
        ############### 1 - direct sound ############################
        self.sources = ra_cpp._direct_sound(self.sources, self.receivers,
            self.rec_radius_init, self.geometry.planes,
            self.c0, self.rays_v.vinit)

        ############### 2 - ray tracing ##############
        self.sources = ra_cpp._raytracer_main(self.ht_length,
            self.allow_scattering, self.transition_order,
            self.rec_radius_init, self.alow_growth, self.rec_radius_final,
            self.sources, self.receivers, self.geometry.planes, self.c0,
            self.rays_v.vinit)

        ######## 3 - Calculate intensities ###################
        res_stat = StatisticalMat(self.geometry, self.freq, self.c0, self.m)
        self.sources = ra_cpp._intensity_main(self.rec_radius_init,
            self.sources, self.c0, self.m, res_stat.alphas_mtx)

        ########### 4 - Process reflectograms and acoustical parameters #####################
        self.sr_results = process_results(self.Dt, self.ht_length,
            self.freq, self.sources, self.receivers)

        # FIXME not sure if this should be part of this method or have a separated one
        # Statistics - my initial sensation - comes hand in hand
        self.stats = SRStats(self.sr_results)

    def run_intensitycalc(self,):
        '''
        Run only the calculation of sound intensity in case the user changes the absorption of a wall
        3 - Intensities must be computed
        4 - Reflectogram, decay and acoustical parameters are computed
        Parts 3 and 4 must be computed if a user chages the absorption of some material in the scene.
        If only the absorption is changed there can be a function to do only these steps.
        '''
        ######## 3 - Calculate intensities ###################
        res_stat = StatisticalMat(self.geometry, self.freq, self.c0, self.m)
        self.sources = ra_cpp._intensity_main(self.rec_radius_init,
            self.sources, self.c0, self.m, res_stat.alphas_mtx)

        ########### 4 - Process reflectograms and acoustical parameters #####################
        self.sr_results = process_results(self.Dt, self.ht_length,
            self.freq, self.sources, self.receivers)

        # FIXME not sure if this should be part of this method or have a separated one
        # Statistics - my initial sensation - comes hand in hand
        self.stats = SRStats(self.sr_results)

    # def set_configs(self, cfgs):
    #     self.cfgs = cfgs['sim_cfg']
    #     self.mat_cfg = cfgs['mat_cfg']
    #     self.controls = AlgControls(self.cfgs['controls'])
    #     self.air = AirProperties(self.cfgs['air'])
    #     self.air_m = self.air.air_absorption(self.controls.freq)

    

    

    

    # def run(self, state):
    #     '''
    #     Parameters:
    #     ----------
    #     Return:
    #     -------
    #         dict with the following structure:
    #         {
    #             'rays':,
    #             ''
    #         }
    #     '''
    #     res_stat = StatisticalMat(
    #         self.geo, self.controls.freq, self.air.c0, self.air_m
    #     )
    #     res_stat.t60_sabine()
    #     res_stat.t60_eyring()
    #     srcs, rcvrs = self.sources, self.receivers
    #     srcs = ra_cpp._direct_sound(
    #         srcs, rcvrs, self.controls.rec_radius_init,
    #         self.geo.planes, self.air.c0, self.rays_i_v.vinit
    #     )
    #     ctls = self.controls
    #     srcs = ra_cpp._raytracer_main(
    #         ctls.ht_length, ctls.allow_scattering, ctls.transition_order,
    #         ctls.rec_radius_init, ctls.alow_growth, ctls.rec_radius_final, srcs,
    #         rcvrs, self.geo.planes, self.air.c0, self.rays_i_v.vinit
    #     )
    #     srcs = ra_cpp._intensity_main(ctls.rec_radius_init,
    #         srcs, self.air.c0, self.air.m, res_stat.alphas_mtx)
    #     sou = process_results(ctls.Dt, ctls.ht_length,
    #         ctls.freq, srcs, rcvrs)
    #     stats = SRStats(sou)

    # def stats(self,):
    #     pass

    # def save(self,):
    #     '''
    #     Return:
    #     ------
    #         a dict with the state of the simulation.
    #     '''
    #     pass
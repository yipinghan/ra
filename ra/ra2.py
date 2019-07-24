import math
import codecs
import json
import time
# import sys
import collada as co
import numpy as np
import toml
from tqdm import tqdm

from ra import rtrace as rt
from ra.source import (
    # CircleSource, ConicSource,
    IsotropicSource,
    # SingleRaySource
)

import ra_cpp

from ra.rayinidir import RayInitialDirections
# from ra.receivers import Receivers
from ra.receivers import setup_receivers
# from ra.sources import Sources
from ra.sources import setup_sources
from ra.controlsair import AlgControls
from ra.controlsair import AirProperties
from ra.room import Geometry, GeometryMat
from ra.absorption_database import load_matdata_from_mat
from ra.absorption_database import get_alpha_s
from ra.statistics import StatisticalMat
from ra.ray_initializer import ray_initializer



def main():

    ##### Test Alg controls ########
    controls = AlgControls('simulation.toml')
    # controls.setup_controls()
    # print(controls.Nrays)
    # print(controls.freq)
    # print(controls.Dt)
    # print(controls.alow_growth)

    ##### Test Alg controls ########
    air = AirProperties('simulation.toml')
    air_m = air.air_absorption(controls.freq)
    # print(air.rho0)
    # print(air.c0)
    # print(air.m)

    ##### Test materials #############
    alpha_list = load_matdata_from_mat('simulation.toml')
    alpha, s = get_alpha_s('simulation.toml', 'surface_mat_id.toml', alpha_list)
    ##### Test Geometry ###########
    geo = GeometryMat('simulation.toml', alpha, s)
    # geo.plot_mat_room(normals = 'on')
    # geo = Geometry('simulation.toml', alpha, s)
    # geo.plot_dae_room(normals = 'on')

    ## Let us test a single plane interception
    # v_in = np.array([0., 0., 1.])#np.array([0.7236, -0.5257, 0.4472])
    # ray_origin = np.array([3.0, 2.333, 1.2])
    # for jplane, plane in enumerate(geo.planes):
    #     # Rp = plane.refpoint3d(ray_origin, v_in)
    #     # wn = plane.test_single_plane(ray_origin, v_in, Rp)
    #     # if wn != 0:
    #     #     print("Reflection point is: {}.".format(Rp))
    #     #     print("Plane {} instersection is: {}. 0 is out"
    #     #         .format(jplane+1, wn))
    #     print("Plane name: {} - {}.".format(plane.name, jplane))
    #     print("Plane normal: {}.".format(plane.normal))
    #     print("Plane nig: {}.".format(plane.nig))
    #     print("Plane vertices: {}.".format(plane.vertices))
    #     print("Plane v_x: {}. Plane v_y: {}.".format(plane.vert_x, plane.vert_y))
    #     print("##################################################################")
    #     # print("Plane area: {}.".format(plane.area))
    #     # print("Plane centroid: {}.".format(plane.centroid))
    #     # print("Plane absorption coefficient: {}.".format(plane.alpha))
    #     # print("Plane scaterring coefficient: {}.".format(plane.s))
    # # print("The total area is {} m2.".format(geo.total_area))
    # # print("The volume is {} m3.".format(geo.volume))


    ##### Test ray initiation ########
    rays_i_v = RayInitialDirections()
    rays_i_v.single_ray([1.0, 0.0, 0.0])#([0.7236, -0.5257, 0.4472])
    # rays_i_v.isotropic_rays(10000) # 15
    # rays_i_v.random_rays(1000)
    # rays_i_v.single_ray(rays_i_v.vinit[41])
    # print(rays_i_v.vinit)
    print("The number of rays is {}.".format(rays_i_v.Nrays))
    # rays_i_v.random_rays(5)
    # rays_i_v.single_ray(rays_i_v.vinit[3]) #([-0.951057, -0.16246, -0.262866])
    # print(rays_i_v.vinit)
    # rays_i_v.plot_arrows()
    # rays_i_v.plot_points()
    # print("Rays original directions: {}.".format(rays_i_v.vinit))

    ##### Test receiver initiation ########
    receivers, reccross, reccrossdir = setup_receivers('simulation.toml')
    # for jrec, r in enumerate(receivers):
    #     print("Receiver {} coord: {}.".format(jrec, r.coord))
    #     # r.orientation = r.point_to_source(np.array(sources[1].coord))
    #     print("Receiver {} orientation: {}.".format(jrec, r.orientation))


    #### Initializa the ray class ########################
    N_max_ref = math.ceil(1.5 * air.c0 * controls.ht_length * \
        (geo.total_area / (4 * geo.volume)))
    # N_max_ref = 100
    # print(rays_i_v.vinit)
    rays = ray_initializer(rays_i_v, N_max_ref, reccross)
    # print(rays[0].planes_hist)
    # print(sys.getsizeof(rays[0].planes_hist))
    ##### Test sources initiation ########
    sources = setup_sources('simulation.toml', rays, reccrossdir)
    
    # for js, s in enumerate(sources):
    #     print("Source {} coord: {}.".format(js, s.coord))
    #     print("Source {} orientation: {}.".format(js, s.orientation))
    #     print("Source {} power dB: {}.".format(js, s.power_dB))
    #     print("Source {} eq dB: {}.".format(js, s.eq_dB))
    #     print("Source {} power (linear): {}.".format(js, s.power_lin))
    #     print("Source {} delay: {}. [s]".format(js, s.delay))

    

    ##### Test statistical theory ############
    # res_stat = StatisticalMat(geo, controls.freq, air.c0, air_m)
    # res_stat.t60_sabine()
    # res_stat.t60_eyring()
    # res_stat.t60_kutruff(gamma=0.4)
    # res_stat.t60_araup()
    # res_stat.t60_fitzroy()
    # res_stat.t60_milsette()
    # res_stat.plot_t60()

    ############### direct sound ############################
    sources = ra_cpp._direct_sound(sources, receivers, controls.rec_radius_init,
        geo.planes, air.c0, rays_i_v.vinit)
    print("test i_dir invoking from c++ {}.".format(sources[0].reccrossdir[0].i_dir))

    ############### Some ray tracing in python ##############
    sources = ra_cpp._raytracer_main(controls.ht_length,
        controls.allow_scattering, controls.transition_order,
        controls.rec_radius_init, controls.alow_growth, controls.rec_radius_final,
        sources, receivers, geo.planes, air.c0,
        rays_i_v.vinit)
    
    sources[0].reccrossdir[0].i_dir = sources[0].reccrossdir[0].intensity_dir(
        sources[0].power_lin, controls.Nrays,
        air.c0, controls.rec_radius_init,
        air.m
    )
    print("test i_dir invoking from python {}.".format(sources[0].reccrossdir[0].i_dir))
    # print("test resturned {}.".format(I))

    # geo.plot_raypath(sources[0].coord, sources[0].rays[0].refpts_hist,
    #     receivers)
    print("plane history")
    print(sources[0].rays[0].planes_hist)
    print("time cross")
    print(sources[0].rays[0].recs[0].time_cross)
    for js, s in enumerate(sources):
        for jrecc, rc in enumerate(reccrossdir):
            print("Source {} : Rec {} - t_dir: {} [s] / n_hits: {}.".format(js, jrecc,
                sources[js].reccrossdir[jrecc].time_dir,
                sources[js].reccrossdir[jrecc].hits_dir))
    
    # print("radius at cross")
    # print(sources[0].rays[0].recs[0].rad_cross)
    # print("ref order at cross")
    # print(sources[0].rays[0].recs[0].ref_order)
    # print("direct time")
    # print(sources[0].reccrossdir[0].time_dir)
    # print("Bytes for {} reflections in plane hist is: {}".format(
    #     N_max_ref, rays[0].planes_hist.itemsize * rays[0].planes_hist.size))
    # print("Bytes for {} reflections in ref pts hist is: {}".format(
    #     N_max_ref, rays[0].refpts_hist.itemsize * rays[0].refpts_hist.size))
    # test = np.zeros((N_max_ref, 3), dtype=np.float64)
    # print(test.itemsize * test.size)
    # print("Simulation is over")
    # print(rays[0].planes_hist)
    # pet = ra_cpp.Pet('pluto', 5)
    # print(pet.get_name())
    # ra_cpp.ray_tracer(air)
    # for js, s in enumerate(sources):
    #     for jray, ray in enumerate(rays_i_v.vinit)

# test array
# ar = [[[[0.001, 0.002], [0.0015], [0.01, 0.025, 0.028]],
#     [[], [0.0017], [0.012, 0.023]]],
#     [[[], [0.0015], []],
#     [[], [0.0017], []]]]
# s1_ray1_rec2 = ar[0][0][1]
# s1_ray2_rec3 = ar[0][1][0]
# s2_ray1_rec2 = ar[0][0][1]
# print(s1_ray1_rec2)
# print(s1_ray2_rec3)
# print(s2_ray1_rec2)
if __name__ == '__main__':
    main()

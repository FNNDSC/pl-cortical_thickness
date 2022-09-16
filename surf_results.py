#!/usr/bin/env python
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from argparse import ArgumentParser, Namespace, ArgumentDefaultsHelpFormatter
from importlib.metadata import Distribution
import subprocess as sp
import math
from tempfile import NamedTemporaryFile
from typing import Optional, Iterable

import numpy as np

from chris_plugin import chris_plugin, PathMapper
from loguru import logger

__pkg = Distribution.from_name(__package__)
__version__ = __pkg.version


DISPLAY_TITLE = r"""
       _                      _   _           _  _   _     _      _                        
      | |                    | | (_)         | || | | |   (_)    | |                       
 _ __ | |______ ___ ___  _ __| |_ _  ___ __ _| || |_| |__  _  ___| | ___ __   ___  ___ ___ 
| '_ \| |______/ __/ _ \| '__| __| |/ __/ _` | || __| '_ \| |/ __| |/ / '_ \ / _ \/ __/ __|
| |_) | |     | (_| (_) | |  | |_| | (_| (_| | || |_| | | | | (__|   <| | | |  __/\__ \__ \
| .__/|_|      \___\___/|_|   \__|_|\___\__,_|_| \__|_| |_|_|\___|_|\_\_| |_|\___||___/___/
| |                                          ______                                        
|_|                                         |______|                                       


"""

parser = ArgumentParser(description='A ChRIS plugin wrapper for cortical_thickness and friends',
                        formatter_class=ArgumentDefaultsHelpFormatter)
parser.add_argument('--mid', default='mid_81920.obj', type=str,
                    help='mid surface output file name')
parser.add_argument('--tlink-thickness', default='tlink.txt', type=str,
                    help='thickness output file name')
parser.add_argument('--surface_angles', default='surface_angles.txt', type=str,
                    help='surface angles output file name')
parser.add_argument('--rad-angles', default='rad_angles.txt', type=str,
                    help='angles (inverted function of surface_angles) output file name')
parser.add_argument('--angles-between-normals', default='angles_between_normals.txt', type=str,
                    help='angles between normals output file name')
parser.add_argument('--scaled-rad-angles', default='scaled_rad_angles.txt', type=str,
                    help='rad angles multiplied by tlink thickness output file name')
parser.add_argument('--scaled-angles-between-normals', default='scaled_angles_between_normals.txt', type=str,
                    help='scaled angles between normals output file name')
parser.add_argument('-V', '--version', action='version',
                    version=f'%(prog)s {__version__}')


# documentation: https://fnndsc.github.io/chris_plugin/chris_plugin.html#chris_plugin
@chris_plugin(
    parser=parser,
    title='Cortical Thickness',
    category='Surfaces',
    min_memory_limit='200Mi',
    min_cpu_limit='1000m',
    min_gpu_limit=0
)
def main(options: Namespace, inputdir: Path, outputdir: Path):
    print(DISPLAY_TITLE, flush=True, file=sys.stderr)

    nproc = len(os.sched_getaffinity(0))
    logger.info('Using {} threads.', nproc)

    mapper = PathMapper.dir_mapper_deep(inputdir, outputdir)
    try:
        with ThreadPoolExecutor(max_workers=nproc) as pool:
            results = pool.map(lambda t: process_one(t[0], t[1], options), mapper)
    except KeyboardInterrupt:
        pool.shutdown(cancel_futures=True)
        raise
    for _ in results:
        pass


_invert_angles = np.vectorize(lambda a: math.acos(1.0 / a))


def process_one(input_dir: Path, output_dir: Path, options):
    # input file names
    inner_surface, outer_surface = choose_inputs(input_dir)
    if not inner_surface or not outer_surface:
        logger.warning('Input files not found, skipping: {}', input_dir)
        return
    # output file names
    mid_surface = output_dir / options.mid
    thickness = output_dir / options.tlink_thickness
    surface_angles = output_dir / options.surface_angles
    rad_angles = output_dir / options.rad_angles
    norm_angles = output_dir / options.angles_between_normals
    scaled_rad_angles = output_dir / options.scaled_rad_angles
    scaled_norm_angles = output_dir / options.scaled_angles_between_normals

    # external program calls
    tasks = (
        ('cortical_thickness', '-tlink', inner_surface, outer_surface, thickness),
        ('average_objects', mid_surface, inner_surface, outer_surface),
        ('adapt_object_mesh', mid_surface, mid_surface, '0', '10', '0', '0'),
        ('surface_angles', inner_surface, mid_surface, outer_surface, surface_angles)
    )

    logger.info('Processing: {}', input_dir)

    for task in tasks:
        run(task)

    # numpy work
    surface_angles_data = np.loadtxt(surface_angles, dtype=np.float32)
    rad_angles_data = _invert_angles(surface_angles_data)
    np.savetxt(rad_angles, rad_angles_data, fmt='%f')

    norm_angles_data = angles_between_normals(inner_surface, outer_surface)
    np.savetxt(norm_angles, norm_angles_data, fmt='%f')  # type: ignore

    thickness_data = np.loadtxt(thickness, dtype=np.float32)
    # normalize values between 0 and 1
    normalized_thickness_data = thickness_data - thickness_data.min()
    normalized_thickness_data /= normalized_thickness_data.max()
    # scale rad angles by normalized thickness data
    scaled_rad_angles_data = rad_angles_data * normalized_thickness_data
    np.savetxt(scaled_rad_angles, scaled_rad_angles_data, fmt='%f')
    # scale normal vector angles by normalized thickness data
    scaled_norm_angles_data = norm_angles_data * normalized_thickness_data
    np.savetxt(scaled_norm_angles, scaled_norm_angles_data, fmt='%f')


def depth_potential_normals(input_filename: str | Path, dtype=np.float32):
    with NamedTemporaryFile(delete=False) as tmp:
        pass
    run(('depth_potential', '-normals', input_filename, tmp.name))  # type: ignore
    data = np.loadtxt(tmp.name, dtype=dtype)
    os.unlink(tmp.name)
    return data


def angle_between(vectors: Iterable[Iterable[float]]):
    return np.arccos(np.clip(np.dot(*vectors), -1.0, 1.0))


def angles_between_normals(inner_filename, outer_filename):
    inner = depth_potential_normals(inner_filename)
    outer = depth_potential_normals(outer_filename)
    # angle between two normal vectors
    return [angle_between(vectors) for vectors in zip(inner, outer)]


def choose_inputs(input_dir: Path) -> tuple[Optional[Path], Optional[Path]]:
    return (
        next(input_dir.glob('*inner*_81920.obj'), None),
        next(input_dir.glob('*outer*_81920.obj'), None)
    )


def run(command_array: tuple[str | os.PathLike]):
    return sp.run(command_array, stdout=sp.DEVNULL, check=True)


if __name__ == '__main__':
    main()

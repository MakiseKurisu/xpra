#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from zlib import crc32
from time import monotonic

from xpra.util.env import envbool
from xpra.util.str_fn import strtobytes

try:
    from xpra.server.window import motion
    log = motion.log        #@UndefinedVariable
except ImportError:
    motion = None


SHOW_PERF = envbool("XPRA_SHOW_PERF")


class TestMotion(unittest.TestCase):

    def calculate_distances(self, array1, array2, min_hits=2, max_distance=1000):
        assert len(array1)==len(array2)
        rect = (0, 0, 1, len(array1))
        return self.do_calculate_distances(rect, array1, array2, min_hits, max_distance)

    def do_calculate_distances(self, rect, array1, array2, min_hits=2, max_distance=1000):
        sd = motion.ScrollData(*rect)
        sd.test_update(array1)
        sd.test_update(array2)
        sd.calculate(max_distance)
        return sd.get_scroll_values(min_hits)

    def test_simple(self):
        self.calculate_distances([0], [1], 0, 100)

    def test_match_distance(self):
        def t(a1, a2, distance, matches):
            scrolls = self.calculate_distances(a1, a2, 0)[0]
            line_defs = scrolls.get(distance)
            assert line_defs, "distance %i not found in scroll data: %s for a1=%s, a2=%s" % (distance, scrolls, a1, a2)
            linecount = sum(line_defs.values())
            assert linecount==matches, "expected %i matches for distance=%i but got %i for a1=%s, a2=%s, result=%s" % (
                matches, distance, linecount, a1, a2, line_defs)
        for N in (motion.MIN_LINE_COUNT+1, 10, 100):
            a = range(1, N+1)
            t(a, a, 0, N)        #identity: all match

            a = [1]*N
            t(a, a, 0, N)

        #from a1 to a2: shift by 2, get 6 hits
        t([3, 4, 5, 6, 7, 8, 9, 10], [1, 2, 3, 4, 5, 6, 7, 8], 2, 6)
        #from a2 to a1: shift by -2, get 6 hits
        t([1, 2, 3, 4, 5, 6, 7, 8], [3, 4, 5, 6, 7, 8, 9, 10], -2, 6)
        N = 100
        S = 1
        a1 = range(S, S+N)
        for M in (motion.MIN_LINE_COUNT, motion.MIN_LINE_COUNT+1, motion.MIN_LINE_COUNT+10, 90):
            a2 = range(M, M+N)
            t(a1, a2, S-M, S+N-M)
            t(a2, a1, M-S, S+N-M)

    # noinspection PyTypeChecker
    def test_calculate_distances(self):
        array1 = [crc32(strtobytes(x)) for x in (1234, b"abc", 99999)]
        array2 = array1[:]
        d = self.calculate_distances(array1, array2, 1)[0]
        assert len(d)==1 and sum(d[0].values())==len(array1), "expected %i matches but got %s" % (len(array1), d[0])

        array1 = range(1, 5)
        array2 = range(2, 6)
        d = self.calculate_distances(array1, array2)[0]
        assert len(d)==1, "expected 1 match but got: %s" % len(d)
        common = set(array1).intersection(set(array2))
        assert -1 in d, "expected distance of -1 but got: %s" % d.keys()
        linecount = sum(d.get(-1, {}).values())
        assert linecount==len(common), "expected %i hits but got: %s" % (len(common), linecount)

        def cdf(v1, v2):
            try:
                self.calculate_distances(v1, v2, 1)
            except Exception:
                return
            else:
                raise Exception("calculate_distances should have failed for values: %s, %s" % (v1, v2))
        cdf(None, None)
        cdf([], None)
        cdf(None, [])
        cdf([1, 2], [1])

        #performance:
        N = 10 if not SHOW_PERF else 4096
        start = monotonic()
        array1 = range(N)
        array2 = [N*2-x*2 for x in range(N)]
        d = self.calculate_distances(array1, array2, 1)[0]
        end = monotonic()
        if SHOW_PERF:
            log.info("calculate_distances %4i^2 in %5.1f ms" % (N, (end-start)*1000))

    def test_detect_motion(self):
        self.do_test_detect_motion(5, 5)
        self.do_test_detect_motion(1920, 1080)

    def do_test_detect_motion(self, W, H):
        from xpra.util.env import NumpyImportContext
        with NumpyImportContext("detect-motion", True):
            try:
                from numpy import random, roll
            except ImportError:
                print("WARNING: numpy not found")
                print(" the motion detection test has been skipped")
                return
        BPP = 4
        #W, H, BPP = 2, 4, 4
        LEN = W * H * BPP
        na1 = random.randint(255, size=LEN, dtype="uint8")

        def tobytes(a):
            return a.tobytes()
        buf1 = tobytes(na1)
        #push first image:
        sd = motion.ScrollData(0, 0, W, H)
        #make a new "image" shifted N lines:
        for N in (1, 2, 20, 100):
            if N>H//2:
                break
            sd.update(buf1, 0, 0, W, H, W*BPP, BPP)
            log("picture of height %i scrolled by %i", H, N)
            na2 = roll(na1, -N*W*BPP)
            buf2 = tobytes(na2)
            start = monotonic()
            sd.update(buf2, 0, 0, W, H, W*BPP, BPP)
            end = monotonic()
            if SHOW_PERF:
                log.info("hashed image %ix%i (%.1fMB) in %4.2f ms" % (W, H, len(buf2)//1024//1024, 1000.0*(end-start)))
            start = monotonic()
            sd.calculate()
            sd_data = sd.get_scroll_values(1)
            scrolls, non_scrolls = sd_data
            log("scroll values=%s", dict(scrolls))
            log("non scroll values=%s", dict(non_scrolls))
            end = monotonic()
            if SHOW_PERF:
                log.info("calculated distances %4i^2 in %5.2f ms" % (H, 1000.0*(end-start)))
            line_defs = scrolls.get(-N, {})
            linecount = sum(line_defs.values())
            assert linecount>0, "could not find distance %i in %s" % (N, line_defs)
            assert linecount == (H-N), "expected to match %i lines but got %i" % (H-N, linecount)
        #import binascii
        #log("na1:\n%s" % binascii.hexlify(tobytes(na1)))
        #log("na2:\n%s" % binascii.hexlify(tobytes(na2)))
        #np.set_printoptions(threshold=np.inf)
        #log("na1:\n%s" % (na1, ))
        #log("na2:\n%s" % (na2, ))

    def test_csum_data(self):
        a1=[
            5992220345606009987, 15040563112965825180, 420530012284267555, 3380071419019115782, 14243596304267993264, 834861281570233459, 10803583843784306120, 1379296002677236226,
            11874402007024898787, 18061820378193118025, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057,
            14669207905734636057, 14669207905734636057, 6048597477520792617, 2736806572525204051, 16630099595908746458, 10194355114249600963, 16726784880639428445, 10866892264854763364,
            6367321356510949102, 16626509354687956371, 6309605599425761357, 6893409879058778343, 5414245501850544038, 10339135854757169820, 8701041795744152980, 3604633436491088815,
            9865399393235410477, 10031306284568036792, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057,
            14669207905734636057, 14669207905734636057, 11266963446837574547, 17157005122993541799, 5218869126146608853, 13274228147453099388, 16342723934713827717, 2435034235422505275,
            3689766606612767057, 13721141386368216492, 14859793948180065358, 6883776362280179367, 14582348771255332968, 15418692344756373599, 10241123668249748621, 197976484773286461,
            14610077842739908751, 9629342716869811747, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057,
            14669207905734636057, 14669207905734636057, 6301677547777858738, 13481745547040629090, 11082728931134194933, 3515047519092751608, 17530992646520472518, 11525573497958613731,
            6186650688264051723, 10053681394182111520, 7507461626261938488, 3136410141592758381, 18320341500820189028, 7224279069641644876, 76220613438872403, 12174575413544881100,
            7769327179604108765, 4993163530803732307, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057,
            14669207905734636057, 14669207905734636057, 1011212212406598056, 12369511552952147752, 17332471340354818353, 5562967289984763417, 7276816103432910616, 9095502394548196500,
            3966866363266810705, 15115893782344445994, 2470115778756702218, 11300572931034497831, 13356453083734411092, 12682463388000998283, 12461900100761490812, 16565659067973398797,
            16700371844333341655, 13475749720883007409, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 15095743182479501355, 16652551598896547263,
            18117428461752083731, 16517651160080181273, 16482769665263024512, 16482769665263024512, 16482769665263024512, 16482769665263024512, 16482769665263024512, 16482769665263024512,
            16482769665263024512, 16482769665263024512, 16482769665263024512, 16482769665263024512, 2620400469557574299, 7552116755125697612, 3191732720857892986, 15697817096682717297,
            14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057,
        ]
        a2 = [
            16517651160080181273, 16482769665263024512, 16482769665263024512, 16482769665263024512, 16482769665263024512, 16482769665263024512, 16482769665263024512, 16482769665263024512,
            16482769665263024512, 16482769665263024512, 16482769665263024512, 2620400469557574299, 7552116755125697612, 3191732720857892986, 15697817096682717297, 14669207905734636057,
            14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057,
            14669207905734636057, 7425237873317005741, 15881577514219781533, 5244943483479698162, 1645884179624549962, 6833306483329956671, 3142507118889544939, 14496593126061659900,
            4782446320116037220, 11121580325383588737, 5128902123802403342, 14539804846999948736, 3999126996485638007, 6071163207581089360, 275311871111368509, 1419512211527079444,
            16496147506624837932, 9366935943282992292, 16641602392096942222, 5312414525355881355, 6512670471206739810, 14669207905734636057, 14669207905734636057, 9515221130600033946,
            14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057,
            16962147477217322879, 17777684172941730501, 5134598006302276024, 4495650412094508491, 14496320858648784912, 5882882193233282408, 13142401013874562815, 17213868142308207279,
            5589927236057965940, 4529401611344340209, 3205874171513572790, 9555164747562437240, 14669207905734636057, 14669207905734636057, 14669207905734636057, 9080427549593249618,
            14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 8165205005918492527,
            13352578771313229684, 11590125678725701957, 2006171165294962460, 5731472049560910928, 7815231195191982982, 5992220345606009987, 15040563112965825180, 420530012284267555,
            3380071419019115782, 14243596304267993264, 834861281570233459, 10803583843784306120, 1379296002677236226, 11874402007024898787, 18061820378193118025, 14669207905734636057,
            14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 6048597477520792617,
            2736806572525204051, 16630099595908746458, 10194355114249600963, 16726784880639428445, 10866892264854763364, 6367321356510949102, 16626509354687956371, 6309605599425761357,
            6893409879058778343, 5414245501850544038, 10339135854757169820, 8701041795744152980, 3604633436491088815, 9865399393235410477, 10031306284568036792, 14669207905734636057,
            14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 14669207905734636057, 11266963446837574547,
            17157005122993541799, 5218869126146608853, 13274228147453099388, 16342723934713827717, 2435034235422505275, 3689766606612767057, 13721141386368216492, 14859793948180065358,
        ]
        # distances = motion.scroll_distances(a1[100:400], a2[100:400], 2, 1000)
        x, y, w = 0, 0, 1050
        h = len(a1)
        sd = motion.ScrollData(x, y, w, h)
        sd.test_update(a1)
        sd.test_update(a2)
        sd.calculate(1000)
        scroll, count = sd.get_best_match()
        log(f"best match: {scroll} - {count}")
        raw_scroll, non_scroll = sd.get_scroll_values()
        assert len(non_scroll)>0
        scrolls = []

        def hexstr(v):
            return hex(v).lstrip("0x").rstrip("L")
        for i in range(h):
            log("%2i:    %16s    %16s" % (i, hexstr(a1[i]), hexstr(a2[i])))
        for scroll, line_defs in raw_scroll.items():
            if scroll==0:
                continue
            for line, count in line_defs.items():
                assert y+line+scroll>=0, "cannot scroll rectangle by %i lines from %i+%i" % (scroll, y, line)
                assert y+line+scroll<=h, "cannot scroll rectangle %i high by %i lines from %i+%i (window height is %i)" % (
                    count, scroll, y, line, h)
                scrolls.append((x, y+line, w, count, 0, scroll))


def main():
    if motion:
        unittest.main()


if __name__ == '__main__':
    main()

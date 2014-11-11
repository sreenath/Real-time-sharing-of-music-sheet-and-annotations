# coding=latin-1
'''
Copyright (C) 2012: W.G. Vree
Contributions: M. Tarenskeen, N. Liberg

This program is free software; you can redistribute it and/or modify it under the terms of the
GNU General Public License as published by the Free Software Foundation; either version 2 of
the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU General Public License for more details. <http://www.gnu.org/licenses/gpl.html>.
'''

try:    import xml.etree.cElementTree as E
except: import xml.etree.ElementTree as E
import os, sys, types, re
from fractions import Fraction

VERSION = '50'

note_ornamentation_map = {        # for notations/, modified from EasyABC
    'ornaments/trill-mark':       'T',
    'ornaments/mordent':          'M',
    'ornaments/inverted-mordent': 'P',
    'ornaments/turn':             '!turn!',
    'ornaments/inverted-turn':    '!invertedturn!',
    'ornaments/tremolo':          '!///!',
    'technical/up-bow':           'u',
    'technical/down-bow':         'v',
    'technical/harmonic':         '!open!',
    'technical/open-string':      '!open!',
    'technical/stopped':          '!plus!',
    'articulations/accent':       '!>!',
    'articulations/strong-accent':'!>!',    # compromise
    'articulations/staccato':     '.',
    'articulations/staccatissimo':'!wedge!',
    'fermata':                    '!fermata!',
    'arpeggiate':                 '!arpeggio!',
    'articulations/tenuto':       '!tenuto!',
    'articulations/staccatissimo':'!wedge!', # not sure whether this is the right translation
    'articulations/spiccato':     '!wedge!', # not sure whether this is the right translation
    'articulations/breath-mark':  '!breath!', # this may need to be tested to make sure it appears on the right side of the note
    'articulations/detached-legato': '!tenuto!.',
}

dynamics_map = {    # for direction/direction-type/dynamics/
    'p':    '!p!',
    'pp':   '!pp!',
    'ppp':  '!ppp!',
    'f':    '!f!',
    'ff':   '!ff!',
    'fff':  '!fff!',
    'mp':   '!mp!',
    'mf':   '!mf!',
    'sfz':  '!sfz!',
}

def info (s, warn=1): sys.stderr.write ((warn and '-- ' or '') + s + '\n')

#-------------------
# data abstractions
#-------------------
class Measure:
    def __init__ (s, p):
        s.reset ()
        s.ixp = p       # part number  
        s.ixm = 0       # measure number
        s.mdur = 0      # measure duration (nominal metre value in divisions)
        s.divs = 0      # number of divisions per 1/4

    def reset (s):      # reset each measure
        s.attr = ''     # measure signatures, tempo
        s.lline = ''    # left barline, but only holds ':' at start of repeat, otherwise empty
        s.rline = '|'   # right barline
        s.lnum = ''     # (left) volta number

class Note:
    def __init__ (s, dur=0, n=None):
        s.tijd = 0      # the time in XML division units
        s.dur = dur     # duration of a note in XML divisions
        s.fact = None   # time modification for tuplet notes (num, div)
        s.tup = ['']    # start(s) and/or stop(s) of tuplet
        s.tupabc = ''   # abc tuplet string to issue before note
        s.beam = 0      # 1 = beamed
        s.grace = 0     # 1 = grace note
        s.before = ''   # extra abc string that goes before the note/chord
        s.after = ''    # the same after the note/chord
        s.ns = n and [n] or []  # notes in the chord
        s.lyrs = {}     # {number -> syllabe}

class Elem:
    def __init__ (s, string):
        s.tijd = 0      # the time in XML division units
        s.str = string  # any abc string that is not a note

class Counter:
    def inc (s, key, voice): s.counters [key][voice] = s.counters [key].get (voice, 0) + 1
    def clear (s, vnums):  # reset all counters
        tups = zip (vnums.keys (), len (vnums) * [0])
        s.counters = {'note': dict (tups), 'nopr': dict (tups), 'nopt': dict (tups)}
    def getv (s, key, voice): return s.counters[key][voice]
    def prcnt (s, ip):  # print summary of all non zero counters
        for iv in s.counters ['note']:
            if s.getv ('nopr', iv) != 0:
                info ( 'part %d, voice %d has %d skipped non printable notes' % (ip, iv, s.getv ('nopr', iv)))
            if s.getv ('nopt', iv) != 0:
                info ( 'part %d, voice %d has %d notes without pitch' % (ip, iv, s.getv ('nopt', iv)))
            if s.getv ('note', iv) == 0: # no real notes counted in this voice
                info ( 'part %d, skipped empty voice %d' % (ip, iv))

class Music:
    def __init__(s, bpl, nvlt):
        s.tijd = 0              # the current time
        s.maxtime = 0           # maximum time in a measure
        s.gMaten = []           # [voices,.. for all measures in a part]
        s.gLyrics = []          # [{num: (abc_lyric_string, melis)},.. for all measures in a part]
        s.vnums = {}            # all used voice id's in a part
        s.cnt = Counter ()      # global counter object
        s.vceCnt = 1            # the global voice count over all parts
        s.lastnote = None       # the last real note record inserted in s.voices
        s.bpl = bpl             # the number of bars per line when writing abc
        s.repbra = 0            # true if volta is used somewhere
        s.nvlt = nvlt           # no volta on higher voice numbers

    def initVoices (s, newPart=0):
        s.vtimes, s.voices, s.lyrics = {}, {}, {}
        for v in s.vnums:
            s.vtimes [v] = 0    # {voice: the end time of the last item in each voice}
            s.voices [v] = []   # {voice: [Note|Elem, ..]}
            s.lyrics [v] = []   # {voice: [{num: syl}, ..]}
        if newPart: s.cnt.clear (s.vnums)   # clear counters once per part

    def incTime (s, dt):
        s.tijd += dt
        if s.tijd > s.maxtime: s.maxtime = s.tijd

    def appendElemCv (s, voices, elem):
        for v in voices:
            s.appendElem (v, elem) # insert element in all voices

    def insertElem (s, v, elem):    # insert at the start of voice v in the current measure
        obj = Elem (elem)
        obj.tijd = 0        # because voice is sorted later
        s.voices [v].insert (0, obj)

    def appendObj (s, v, obj, dur):
        obj.tijd = s.tijd
        s.voices [v].append (obj)
        s.incTime (dur)
        if s.tijd > s.vtimes[v]: s.vtimes[v] = s.tijd   # don't update for inserted earlier items

    def appendElem (s, v, elem):
        s.appendObj (v, Elem (elem), 0)

    def appendNote (s, v, note, noot):
        note.ns.append (noot)
        s.appendObj (v, note, int (note.dur))
        if noot != 'z':             # real notes and grace notes
            s.lastnote = note       # remember last note for later modifications (chord, grace)
            s.cnt.inc ('note', v)   # count number of real notes in each voice
            if not note.grace:                  # for every real note
                s.lyrics[v].append (note.lyrs)  # even when it has no lyrics

    def getLastRec (s, voice):
        if s.gMaten: return s.gMaten[-1][voice][-1] # the last record in the last measure
        return None                                 # no previous records in the first measure

    def getLastMelis (s, voice, num):   # get melisma of last measure
        if s.gLyrics:
            lyrdict = s.gLyrics[-1][voice]  # the previous lyrics dict in this voice
            if num in lyrdict: return lyrdict[num][1]   # lyrdict = num -> (lyric string, melisma)
        return 0 # no previous lyrics in voice or line number

    def addChord (s, noot):  # careful: we assume that chord notes follow immediately 
        s.lastnote.ns.append (noot)

    def addBar (s, lbrk, m): # linebreak, measure data
        if m.mdur and s.maxtime > m.mdur: info ('measure %d in part %d longer than metre' % (m.ixm+1, m.ixp+1))
        s.tijd = s.maxtime              # the time of the bar lines inserted here
        for v in s.vnums:
            if m.lline or m.lnum:       # if left barline or left volta number
                p = s.getLastRec (v)    # get the previous barline record
                if p:                   # in measure 1 no previous measure is available
                    x = p.str           # p.str is the ABC barline string
                    if m.lline:         # append begin of repeat, m.lline == ':'
                        x = (x + m.lline).replace (':|:','::').replace ('||','|')
                    if s.nvlt == 3:     # add volta number only to lowest voice in part 0 
                        if m.ixp + v == min (s.vnums): x += m.lnum
                    elif m.lnum:        # new behaviour with I:repbra 0
                        x += m.lnum     # add volta number(s) or text to all voices
                        s.repbra = 1    # signal occurrence of a volta
                    p.str = x           # modify previous right barline
                elif m.lline:           # begin of new part and left repeat bar is required
                    s.insertElem (v, '|:')
            if lbrk:
                p = s.getLastRec (v)    # get the previous barline record
                if p: p.str += lbrk     # insert linebreak char after the barlines+volta
            if m.attr:                  # insert signatures at front of buffer
                s.insertElem (v, '%s' % m.attr)
            s.appendElem (v, ' %s' % m.rline)   # insert current barline record at time maxtime
            s.voices[v] = sortMeasure (s.voices[v], m)  # make all times consistent
            lyrs = s.lyrics[v]          # [{number: sylabe}, .. for all notes]
            lyrdict = {}                # {number: (abc_lyric_string, melis)} for this voice
            nums = [num for d in lyrs for num in d.keys ()] # the lyrics numbers in this measure
            maxNums = max (nums + [0])  # the highest lyrics number in this measure
            for i in range (maxNums, 0, -1):
                xs = [syldict.get (i, '') for syldict in lyrs]  # collect the syllabi with number i
                melis = s.getLastMelis (v, i)  # get melisma from last measure
                lyrdict [i] = abcLyr (xs, melis)
            s.lyrics[v] = lyrdict       # {number: (abc_lyric_string, melis)} for this measure
            mkBroken (s.voices[v])
        s.gMaten.append (s.voices)
        s.gLyrics.append (s.lyrics)
        s.tijd = s.maxtime = 0
        s.initVoices ()

    def outVoices (s, divs, ip):    # output all voices of part ip
        vvmap = {}                  # xml voice number -> abc voice number (one part)
        lvc = min (s.vnums.keys ()) # lowest xml voice number of this part
        for iv in s.vnums:
            if s.cnt.getv ('note', iv) == 0:    # no real notes counted in this voice
                continue            # skip empty voices
            if abcOut.denL: unitL = abcOut.denL # take the unit length from the -d option
            else:           unitL = compUnitLength (iv, s.gMaten, divs) # compute the best unit length for this voice
            abcOut.cmpL.append (unitL)  # remember for header output
            vn, vl = [], {}         # for voice iv: collect all notes to vn and all lyric lines to vl
            for im in range (len (s.gMaten)):
                measure = s.gMaten [im][iv]
                vn.append (outVoice (measure, divs, im, ip, unitL))
                checkMelismas (s.gLyrics, s.gMaten, im, iv)
                for n, (lyrstr, melis) in s.gLyrics [im][iv].items ():
                    if n in vl:
                        while len (vl[n]) < im: vl[n].append ('') # fill in skipped measures
                        vl[n].append (lyrstr)
                    else:
                        vl[n] = im * [''] + [lyrstr]    # must skip im measures
            for n, lyrs in vl.items (): # fill up possibly empty lyric measures at the end
                mis = len (vn) - len (lyrs)
                lyrs += mis * ['']
            abcOut.add ('V:%d' % s.vceCnt)
            if s.repbra:
                if s.nvlt == 1 and s.vceCnt > 1: abcOut.add ('I:repbra 0')  # only volta on first voice
                if s.nvlt == 2 and iv > lvc:     abcOut.add ('I:repbra 0')  # only volta on first voice of each part
            if s.bpl > 0: maxll = s.bpl # command line option: max line length in chars
            else:         maxll = 100   # the default
            bn = 0                      # count bars
            while vn:                   # while still measures available
                ib = 1
                chunk = vn [0]
                while ib < len (vn) and len (chunk) + len (vn [ib]) < maxll:
                    chunk += vn [ib]
                    ib += 1
                bn += ib
                abcOut.add (chunk + ' %%%d' % bn)   # line with barnumer
                del vn[:ib]         # chop ib bars
                lyrlines = vl.items ()
                lyrlines.sort ()    # order the numbered lyric lines for output
                for n, lyrs in lyrlines:
                    abcOut.add ('w: ' + '|'.join (lyrs[:ib]) + '|')
                    del lyrs[:ib]
            vvmap [iv] = s.vceCnt   # xml voice number -> abc voice number
            s.vceCnt += 1           # count voices over all parts
        s.gMaten = []               # reset the follwing instance vars for each part
        s.gLyrics = []
        s.cnt.prcnt (ip+1)          # print summary of skipped items in this part
        return vvmap

class ABCoutput:
    def __init__ (s, fnm, pad, X, denL, volpan):
        s.fnm = fnm
        s.outlist = []          # list of ABC strings
        s.title = 'T:Title'
        s.key = 'none'
        s.clefs = {}            # clefs for all abc-voices
        s.mtr = 'none'
        s.tempo = 0             # 0 -> no tempo field
        s.pad = pad             # the output path or none
        s.X = X + 1             # the abc tune number
        s.denL = denL           # denominator of the unit length (L:) from -d option
        s.volpan = volpan       # true -> also output midi volume and panning
        s.cmpL = []             # computed optimal unit length for all voices
        if pad: s.outfile = file (os.path.join (pad, fnm), 'w') # the ABC output file
        else:   s.outfile = sys.stdout

    def add (s, str):
        s.outlist.append (str + '\n')   # collect all ABC output

    def mkHeader (s, stfmap, partlist, midimap): # stfmap = [parts], part = [staves], stave = [voices]
        accVce, accStf, staffs = [], [], stfmap[:]  # staffs is consumed
        for x in partlist:              # collect partnames into accVce and staff groups into accStf
            try: prgroupelem (x, ('', ''), '', stfmap, accVce, accStf)
            except: info ('lousy musicxml: error in part-list')
        staves = ' '.join (accStf)
        clfnms = {}
        for part, (partname, partabbrv) in zip (staffs, accVce):
            if not part: continue       # skip empty part
            firstVoice = part[0][0]     # the first voice number in this part
            nm  = partname.replace ('\n','\\n').replace ('.:','.').strip (':')
            snm = partabbrv.replace ('\n','\\n').replace ('.:','.').strip (':')
            clfnms [firstVoice] = (nm and 'nm="%s"' % nm or '') + (snm and ' snm="%s"' % snm or '')
        hd = ['X:%d\n%s\n' % (s.X, s.title)]
        if staves and len (accStf) > 1: hd.append ('%%score ' + staves + '\n')
        tempo = s.tempo and 'Q:1/4=%s\n' % s.tempo or ''    # default no tempo field
        d = {}  # determine the most frequently occurring unit length over all voices
        for x in s.cmpL: d[x] = d.get (x, 0) + 1
        defL = sorted (d.items (), key=lambda x:x[1], reverse=1)[0][0]
        defL = s.denL and s.denL or defL    # override default unit length with -d option
        hd.append ('L:1/%d\n%sM:%s\n' % (defL, tempo, s.mtr))
        hd.append ('I:linebreak $\nK:%s\n' % s.key)
        for vnum, clef in s.clefs.items ():
            hd.append ('V:%d %s %s\n' % (vnum, clef, clfnms.get (vnum, '')))
            ch, prg, vol, pan = midimap [vnum-1]
            if s.volpan:    # -m option -> output all recognized midi commands when needed and present in xml
                if ch > 0 and ch != vnum: hd.append ('%%%%MIDI channel %d\n' % ch)
                if prg > 0:  hd.append ('%%%%MIDI program %d\n' % (prg - 1))
                if vol >= 0: hd.append ('%%%%MIDI control 7 %.0f\n' % vol)  # volume == 0 is possible ...
                if pan >= 0: hd.append ('%%%%MIDI control 10 %.0f\n' % pan)
            else:           # default -> only output midi program command when present in xml
                if prg > 0:  hd.append ('%%%%MIDI program %d\n' % (prg - 1))
            if defL != s.cmpL [vnum-1]: # only if computed unit length different from header
                hd.append ('L:1/%d\n' % s.cmpL [vnum-1])
        s.outlist = hd + s.outlist

    def writeall (s):  # determine the required encoding of the entire ABC output
        str = ''.join (s.outlist)
        try:    s.outfile.write (str.encode ('latin-1'))    # prefer latin-1
        except: s.outfile.write (str.encode ('utf-8'))      # fall back to utf if really needed
        if s.pad: s.outfile.close ()                        # close each file with -o option
        else: s.outfile.write ('\n')                        # add empty line between tunes on stdout
        info ('%s.abc written with %d voices' % (s.fnm, len (s.clefs)), warn=0)

#----------------
# functions
#----------------
def abcLyr (xs, melis): # Convert list xs to abc lyrics.
    if not ''.join (xs): return '', 0  # there is no lyrics in this measure
    res = []
    for x in xs:        # xs has for every note a lyrics syllabe or an empty string
        if x == '':     # note without lyrics
            if melis: x = '_'   # set melisma
            else: x = '*'       # skip note
        elif x.endswith ('_') and not x.endswith ('\_'): # start of new melisma
            x = x.replace ('_', '') # remove and set melis boolean
            melis = 1           # so next skips will become melisma
        else: melis = 0         # melisma stops on first syllable
        res.append (x)
    return (' '.join (res), melis)

def simplify (a, b):    # divide a and b by their greatest common divisor
    x, y = a, b
    while b: a, b = b, a % b
    return x / a, y / a

def abcdur (nx, divs, uL):      # convert an musicXML duration d to abc units with L:1/uL
    if nx.dur == 0: return ''   # when called for elements without duration
    num, den = simplify (uL * nx.dur, divs * 4) # L=1/8 -> uL = 8 units
    if nx.fact:                 # apply tuplet time modification
        numfac, denfac = nx.fact
        num, den = simplify (num * numfac, den * denfac)
    if den > 64:                # limit the denominator to a maximum of 64
        f = Fraction (num, den).limit_denominator (64)
        num, den = f.numerator, f.denominator
    if num == 1:
        if   den == 1: dabc = ''
        elif den == 2: dabc = '/'
        else:          dabc = '/%d' % den
    elif den == 1:     dabc = '%d' % num
    else:              dabc = '%d/%d' % (num, den)
    return dabc

def setKey (fifths, mode):
    accs = ['F','C','G','D','A','E','B']
    kmaj = ['Cb','Gb','Db','Ab','Eb','Bb','F','C','G','D','A', 'E', 'B', 'F#','C#']
    kmin = ['Ab','Eb','Bb','F', 'C', 'G', 'D','A','E','B','F#','C#','G#','D#','A#']
    key = ''
    if mode == 'major': key = kmaj [7 + fifths]
    if mode == 'minor': key = kmin [7 + fifths] + 'min'
    if fifths >= 0: msralts = dict (zip (accs[:fifths], fifths * [1]))
    else:           msralts = dict (zip (accs[fifths:], -fifths * [-1]))
    return key, msralts

def insTup (ix, notes, fact):   # read one nested tuplet
    tupcnt, halted = 0, 0
    nx = notes [ix]
    if 'start' in nx.tup:
        nx.tup.remove ('start') # do recursive calls when starts remain
    tix = ix                    # index of first tuplet note
    fn, fd = fact               # xml time-mod of the higher level
    fnum, fden = nx.fact        # xml time-mod of the current level
    tupfact = fnum/fn, fden/fd  # abc time mod of this level
    while ix < len (notes):
        nx = notes [ix]
        if isinstance (nx, Elem) or nx.grace:
            ix += 1             # skip all non tuplet elements
            continue
        if 'start' in nx.tup:   # more nested tuplets to start
            ix, tupcntR = insTup (ix, notes, tupfact)   # ix is on the stop note!
            tupcnt += tupcntR
        elif nx.fact:
            tupcnt += 1         # count tuplet elements
        if 'stop' in nx.tup:
            nx.tup.remove ('stop')
            halted = 1
            break
        if not nx.fact:         # stop on first non tuplet note
            ix = lastix         # back to last tuplet note
            halted = 1
            break
        lastix = ix
        ix += 1
    # put abc tuplet notation before the recursive ones
    tup = (tupfact[0], tupfact[1], tupcnt)
    if tup == (3, 2, 3): tupPrefix = '(3'
    else:                tupPrefix = '(%d:%d:%d' % tup
    notes [tix].tupabc = tupPrefix + notes [tix].tupabc
    return ix, tupcnt           # ix is on the last tuplet note

def mkBroken (vs):      # introduce broken rhythms (vs: one voice, one measure)
    vs = [n for n in vs if isinstance (n, Note)]
    i = 0
    while i < len (vs) - 1:
        n1, n2 = vs[i], vs[i+1]     # scan all adjacent pairs
        # skip if note in tuplet or has no duration or outside beam
        if not n1.fact and not n2.fact and n1.dur > 0 and n2.beam:
            if n1.dur * 3 == n2.dur:
                n2.dur = (2 * n2.dur) / 3
                n1.dur = n1.dur * 2
                n1.after = '<' + n1.after
                i += 1              # do not chain broken rhythms
            elif n2.dur * 3 == n1.dur:
                n1.dur = (2 * n1.dur) / 3
                n2.dur = n2.dur * 2
                n1.after = '>' + n1.after
                i += 1              # do not chain broken rhythms
        i += 1

def outVoice (measure, divs, im, ip, unitL):    # note/elem objects of one measure in one voice
    ix = 0
    while ix < len (measure):   # set all (nested) tuplet annotations
        nx = measure [ix]
        if isinstance (nx, Note) and nx.fact:
            ix, tupcnt = insTup (ix, measure, (1, 1))   # read one tuplet, insert annotation(s)
        ix += 1 
    vs = []
    for nx in measure:
        if isinstance (nx, Note):
            durstr = abcdur (nx, divs, unitL)           # xml -> abc duration string
            chord = len (nx.ns) > 1
            cns = [nt[:-1] for nt in nx.ns if nt.endswith ('-')]
            tie = ''
            if chord and len (cns) == len (nx.ns):      # all chord notes tied
                nx.ns = cns     # chord notes without tie
                tie = '-'       # one tie for whole chord
            s = nx.tupabc + nx.before
            if chord: s += '['
            for nt in nx.ns: s += nt
            if chord: s += ']' + tie
            if s.endswith ('-'): s, tie = s[:-1], '-'   # split off tie
            s += durstr + tie   # and put it back again
            s += nx.after
            nospace = nx.beam
        else:
            s = nx.str
            nospace = 1
        if nospace: vs.append (s)
        else: vs.append (' ' + s)
    return (''.join (vs))

def sortMeasure (voice, m):
    voice.sort (key=lambda o: o.tijd)   # sort on time
    time = 0
    v = []
    for nx in voice:    # establish sequentiality
        if nx.tijd > time: v.append (Note (nx.tijd - time, 'x')) # fill hole
        if isinstance (nx, Elem):
            if nx.tijd < time: nx.tijd = time # shift elems without duration to where they fit
            v.append (nx)
            time = nx.tijd
            continue
        if nx.tijd < time:                  # overlapping element
            if nx.ns[0] == 'z': continue    # discard overlapping rest
            if v[-1].tijd <= nx.tijd:       # we can do something
                if v[-1].ns[0] == 'z':      # shorten rest
                    v[-1].dur = nx.tijd - v[-1].tijd
                    if v[-1].dur == 0: del v[-1]        # nothing left
                    info ('overlap in part %d, measure %d: rest shortened' % (m.ixp+1, m.ixm+1))
                else:                       # make a chord of overlap
                    v[-1].ns += nx.ns
                    info ('overlap in part %d, measure %d: added chord' % (m.ixp+1, m.ixm+1))
                    nx.dur = (nx.tijd + nx.dur) - time  # the remains
                    if nx.dur <= 0: continue            # nothing left
                    nx.tijd = time          # append remains
            else:                           # give up
                info ('overlapping notes in one voice! part %d, measure %d, note %s discarded' % (m.ixp+1, m.ixm+1, isinstance (nx, Note) and nx.ns or nx.str))
                continue
        v.append (nx)
        time = nx.tijd + nx.dur
    #   when a measure contains no elements and no forwards -> no incTime -> s.maxtime = 0 -> right barline
    #   is inserted at time == 0 (in addbar) and is only element in the voice when sortMeasure is called
    if time == 0: info ('empty measure in part %d, measure %d, it should contain at least a rest to advance the time!' % (m.ixp+1, m.ixm+1))
    return v

def getPartlist (ps):   # correct part-list (from buggy xml-software)
    xs = [] # the corrected part-list
    e = []  # stack of opened part-groups
    for x in ps.getchildren (): # insert missing stops, delete double starts
        if x.tag ==  'part-group':
            num, type = x.get ('number'), x.get ('type')
            if type == 'start':
                if num in e:    # missing stop: insert one
                    xs.append (E.Element ('part-group', number = num, type = 'stop'))
                    xs.append (x)
                else:           # normal start
                    xs.append (x)
                    e.append (num)
            else:
                if num in e:    # normal stop
                    e.remove (num)
                    xs.append (x)
                else: pass      # double stop: skip it
        else: xs.append (x)
    for num in reversed (e):    # fill missing stops at the end
        xs.append (E.Element ('part-group', number = num, type = 'stop'))
    return xs

def parseParts (xs, d, e):  # -> [elems on current level], rest of xs
    if not xs: return [],[]
    x = xs.pop (0)
    if x.tag == 'part-group':
        num, type = x.get ('number'), x.get ('type')
        if type == 'start': # go one level deeper
            s = [x.findtext (n, '') for n in ['group-symbol','group-barline','group-name','group-abbreviation']]
            d [num] = s     # remember groupdata by group number
            e.append (num)  # make stack of open group numbers
            elemsnext, rest1 = parseParts (xs, d, e) # parse one level deeper to next stop
            elems, rest2 = parseParts (rest1, d, e)  # parse the rest on this level
            return [elemsnext] + elems, rest2
        else:               # stop: close level and return group-data
            nums = e.pop () # last open group number in stack order
            if xs and xs[0].get ('type') == 'stop':     # two consequetive stops
                if num != nums:                         # in the wrong order (tempory solution)
                    d[nums], d[num] = d[num], d[nums]   # exchange values    (only works for two stops!!!)
            sym = d[num]    # retrieve an return groupdata as last element of the group
            return [sym], xs
    else:
        elems, rest = parseParts (xs, d, e) # parse remaining elements on current level
        name = x.findtext ('part-name',''), x.findtext ('part-abbreviation','')
        return [name] + elems, rest

def bracePart (part):       # put a brace on multistaff part and group voices
    if not part: return []  # empty part in the score
    brace = []
    for ivs in part:
        if len (ivs) == 1:  # stave with one voice
            brace.append ('%s' % ivs[0])
        else:               # stave with multiple voices
            brace += ['('] + ['%s' % iv for iv in ivs] + [')']
        brace.append ('|')
    del brace[-1]           # no barline at the end
    if len (part) > 1:
        brace = ['{'] + brace + ['}']
    return brace

def prgroupelem (x, gnm, bar, pmap, accVce, accStf):    # collect partnames (accVce) and %%score map (accStf)
    if type (x) == types.TupleType: # partname-tuple = (part-name, part-abbrev)
        y = pmap.pop (0)
        if gnm[0]: x = [n1 + ':' + n2 for n1, n2 in zip (gnm, x)]   # put group-name before part-name
        accVce.append (x)
        accStf.extend (bracePart (y))
    elif len (x) == 2:      # misuse of group just to add extra name to stave
        y = pmap.pop (0)
        nms = [n1 + ':' + n2 for n1, n2 in zip (x[0], x[1][2:])]    # x[0] = partname-tuple, x[1][2:] = groupname-tuple
        accVce.append (nms)
        accStf.extend (bracePart (y))
    else:
        prgrouplist (x, bar, pmap, accVce, accStf)

def prgrouplist (x, pbar, pmap, accVce, accStf):    # collect partnames, scoremap for a part-group
    sym, bar, gnm, gabbr = x[-1]    # bracket symbol, continue barline, group-name-tuple
    bar = bar == 'yes' or pbar      # pbar -> the parent has bar
    accStf.append (sym == 'brace' and '{' or '[')
    for z in x[:-1]:
        prgroupelem (z, (gnm, gabbr), bar, pmap, accVce, accStf)
        if bar: accStf.append ('|')
    if bar: del accStf [-1]         # remove last one before close
    accStf.append (sym == 'brace' and '}' or ']')

def compUnitLength (iv, maten, divs):   # compute optimal unit length
    uLmin, minLen = 0, sys.maxint
    for uL in [4,8,16]:     # try 1/4, 1/8 and 1/16
        vLen = 0            # total length of abc duration strings in this voice
        for m in maten:     # all measures
            for e in m[iv]: # all notes in voice iv
                if isinstance (e, Elem) or e.dur == 0: continue # no real durations
                vLen += len (abcdur (e, divs, uL))  # add len of duration string
        if vLen < minLen: uLmin, minLen = uL, vLen  # remember the smallest
    return uLmin

def doSyllable (syl):
    txt = ''
    for e in syl:
        if   e.tag == 'elision': txt += '~'
        elif e.tag == 'text':   # escape - and space characters
            txt += (e.text or '').replace ('_','\_').replace('-', r'\-').replace(' ', '~')
    if not txt: return txt
    if syl.findtext('syllabic') in ['begin', 'middle']: txt += '-'
    if syl.find('extend') is not None:                  txt += '_'
    return txt

def checkMelismas (lyrics, maten, im, iv):
    if im == 0: return
    maat = maten [im][iv]               # notes of the current measure
    curlyr = lyrics [im][iv]            # lyrics dict of current measure
    prvlyr = lyrics [im-1][iv]          # lyrics dict of previous measure
    for n, (lyrstr, melis) in prvlyr.items ():  # all lyric numbers in the previous measure
        if n not in curlyr and melis:   # melisma required, but no lyrics present -> make one!
            ms = getMelisma (maat)      # get a melisma for the current measure
            if ms: curlyr [n] = (ms, 0) # set melisma as the n-th lyrics of the current measure

def getMelisma (maat):                  # get melisma from notes in maat
    ms = []
    for note in maat:                   # every note should get an underscore
        if not isinstance (note, Note): continue    # skip Elem's
        if note.grace: continue         # skip grace notes
        if note.ns [0] == 'z': break    # stop on first rest
        ms.append ('_')
    return ' '.join (ms)

#----------------
# parser
#----------------
class Parser:
    def __init__ (s, options):
        # unfold repeats, number of chars per line, credit filter level, volta option
        unfold, bpl, ctf, nvlt = options.u, options.n, options.c, options.v
        s.slurBuf = {}    # dict of open slurs keyed by slur number
        s.wedge_type = '' # remembers the type of the last open wedge (for proper closing)
        s.ingrace = 0     # marks a sequence of grace notes
        s.msc = Music (bpl, nvlt)  # global music data abstraction
        s.unfold = unfold # turn unfolding repeats on
        s.ctf = ctf       # credit text filter level
        s.gStfMap = []    # [[abc voice numbers] for all parts]
        s.midiMap = []    # midi-settings for each abc voice, in order
        s.instMid = []    # [{inst id -> midi-settings} for all parts]
        s.midDflt = [-1,-1,-1,-91] # default midi settings for channel, program, volume, panning
        s.msralts = {}    # xml-notenames (without octave) with accidentals from the key
        s.curalts = {}    # abc-notenames (with voice number) with passing accidentals
        s.stfMap = {}     # xml staff number -> [xml voice number]
        s.clefMap = {}    # xml staff number -> clef

    def matchSlur (s, type2, n, v2, note2, grace, stopgrace): # match slur number n in voice v2, add abc code to before/after
        if type2 not in ['start', 'stop']: return   # slur type continue has no abc equivalent
        if n == None: n = '1'
        if n in s.slurBuf:
            type1, v1, note1, grace1 = s.slurBuf [n]
            if type2 != type1:              # slur complete, now check the voice
                if v2 == v1:                # begins and ends in the same voice: keep it
                    if type1 == 'start' and (not grace1 or not stopgrace):  # normal slur: start before stop and no grace slur
                        note1.before = '(' + note1.before   # keep left-right order!
                        note2.after += ')'
                    # no else: don't bother with reversed stave spanning slurs
                del s.slurBuf [n]           # slur finished, remove from stack
            else:                           # double definition, keep the last
                info ('double slur numbers %s-%s in part %d, measure %d, voice %d note %s, first discarded' % (type2, n, s.msr.ixp+1, s.msr.ixm+1, v2, note2.ns))
                s.slurBuf [n] = (type2, v2, note2, grace)
        else:                               # unmatched slur, put in dict
            s.slurBuf [n] = (type2, v2, note2, grace)
    
    def doNotations (s, note, nttn):
        for key, val in note_ornamentation_map.items  ():
            if nttn.find (key) != None: note.before += val  # just concat all ornaments
        fingering = nttn.find ('technical/fingering')
        if fingering != None:   # strings or plug not supported in ABC
            note.before += '!%s!' % fingering.text     # validate text?
        wvln = nttn.find ('ornaments/wavy-line')
        if wvln != None:
            if   wvln.get ('type') == 'start': note.before = '!trill(!' + note.before # keep left-right order!
            elif wvln.get ('type') == 'stop': note.after += '!trill)!'

    def ntAbc (s, ptc, o, note, v):  # pitch, octave -> abc notation
        acc2alt = {'double-flat':-2,'flat-flat':-2,'flat':-1,'natural':0,'sharp':1,'sharp-sharp':2,'double-sharp':2}
        p = ptc
        if o > 4: p = ptc.lower ()
        if o > 5: p = p + (o-5) * "'"
        if o < 4: p = p + (4-o) * ","
        acc = note.findtext ('accidental')  # should be the notated accidental
        alt = note.findtext ('pitch/alter') # pitch alteration (midi)
        if alt == None and s.msralts.get (ptc, 0): alt = 0  # no alt but key implies alt -> natural!!
        if acc == None and alt == None: return p    # no acc, no alt
        elif acc != None:
            alt = acc2alt [acc]
        else:   # now see if we really must add an accidental
            alt = int (alt)
            if (p, v) in s.curalts:  # the note in this voice has been altered before
                if alt == s.curalts [(p, v)]: return p      # alteration still the same
            elif alt == s.msralts.get (ptc, 0): return p    # alteration implied by the key
            if 'stop' in [e.get ('type') for e in note.findall ('tie')]: return p   # don't alter tied notes
            info ('accidental %d added in part %d, measure %d, voice %d note %s' % (alt, s.msr.ixp+1, s.msr.ixm+1, v+1, p))
        s.curalts [(p, v)] = alt
        p = ['__','_','=','^','^^'][alt+2] + p # and finally ... prepend the accidental
        return p

    def doNote (s, n):    # parse a musicXML note tag
        note = Note ()
        v = int (n.findtext ('voice', '1'))
        chord = n.find ('chord') != None
        p = n.findtext ('pitch/step')
        o = n.findtext ('pitch/octave')
        r = n.find ('rest')
        numer = n.findtext ('time-modification/actual-notes')
        if numer:
            denom = n.findtext ('time-modification/normal-notes')
            note.fact = (int (numer), int (denom))
        note.tup = [x.get ('type') for x in n.findall ('notations/tuplet')]
        dur = n.findtext ('duration')
        grc = n.find ('grace')
        note.grace = grc != None
        note.before, note.after = '', '' # strings with ABC stuff that goes before or after a note/chord
        if note.grace and not s.ingrace: # open a grace sequence
            s.ingrace = 1
            note.before = '{'
            if grc.get ('slash') == 'yes': note.before += '/'   # acciaccatura
        stopgrace = not note.grace and s.ingrace
        if stopgrace:                   # close the grace sequence
            s.ingrace = 0
            s.msc.lastnote.after += '}' # close grace on lastenote.after
        if r == None and n.get ('print-object') == 'no': # not a rest and not visible
            s.msc.cnt.inc ('nopr', v)   # count skipped notes
            return                      # skip non printable notes
        if dur == None or note.grace: dur = 0
        note.dur = int (dur)
        if r == None and (not p or not o):  # not a rest and no pitch
            s.msc.cnt.inc ('nopt', v)       # count unpitched notes
            o, p = 5,'E'                    # make it an E5 ??
        nttn = n.find ('notations')     # add ornaments
        if nttn != None: s.doNotations (note, nttn)
        if r != None: noot = 'z'
        else: noot = s.ntAbc (p, int (o), n, v)
        if 'start' in [e.get ('type') for e in n.findall ('tie')]:  # n can have stop and start tie
            noot = noot + '-'
        note.beam = sum ([1 for b in n.findall('beam') if b.text in ['continue', 'end']]) + int (note.grace)
        for e in n.findall ('lyric'):
            lyrnum = int (e.get ('number', '1'))
            note.lyrs [lyrnum] = doSyllable (e)
        if chord: s.msc.addChord (noot)
        else:     s.msc.appendNote (v, note, noot)
        for slur in n.findall ('notations/slur'):   # s.msc.lastnote points to the last real note/chord inserted above
            s.matchSlur (slur.get ('type'), slur.get ('number'), v, s.msc.lastnote, note.grace, stopgrace) # match slur definitions

    def doAttr (s, e): # parse a musicXML attribute tag
        teken = {'C1':'alto1','C2':'alto2','C3':'alto','C4':'tenor','F4':'bass','F3':'bass3','G2':'treble','TAB':'','percussion':'perc'}
        trans = {'treble-8': ' m=B,', 'bass-8': ' m=D,,'}
        dvstxt = e.findtext ('divisions')
        if dvstxt: s.msr.divs = int (dvstxt)
        steps = int (e.findtext ('transpose/chromatic', '0'))   # for transposing instrument
        fifths = e.findtext ('key/fifths')
        first = s.msc.tijd == 0 and s.msr.ixm == 0  # first attributes in first measure
        if fifths:
            key, s.msralts = setKey (int (fifths), e.findtext ('key/mode','major'))
            if first and not steps: abcOut.key = key # first measure -> header, if not transposing instrument!
            else: s.msr.attr += '[K:%s]' % key  # otherwise -> voice
        beats = e.findtext ('time/beats')
        if beats:
            unit = e.findtext ('time/beat-type')
            mtr = beats + '/' + unit
            if first: abcOut.mtr = mtr          # first measure -> header
            else: s.msr.attr += '[M:%s]' % mtr # otherwise -> voice
            s.msr.mdur = (s.msr.divs * int (beats) * 4) / int (unit)    # duration of measure in xml-divisions
        toct = e.findtext ('transpose/octave-change', '')
        if toct: steps += 12 * int (toct)       # extra transposition of toct octaves
        for clef in e.findall ('clef'):         # a part can have multiple staves
            n = int (clef.get ('number', '1'))  # local staff number for this clef
            sgn = clef.findtext ('sign')
            cs = teken.get (sgn + clef.findtext ('line', ''), '')
            oct = clef.findtext ('clef-octave-change')
            if oct: cs += oct == '-1' and '-8' or '+8'
            if cs in trans: cs += trans[cs]     # patchwork: abcm2ps does not transpose the -8 ...
            if steps: cs += ' transpose=' + str (steps)
            if first: s.clefMap [n] = cs        # clef goes to header (where it is mapped to voices)
            else: s.msc.appendElemCv (s.stfMap[n], '[K:%s]' % cs)   # clef change to all voices of staff n

    def doDirection (s, e): # parse a musicXML direction tag
        plcmnt = e.get ('placement')
        t = e.find ('sound')        # there are many possible attributes for sound
        if t != None:
            tempo = t.get ('tempo') # look for tempo attribute
            if tempo:
                if '.' in tempo: tempo = '%.2f' % float (tempo) # hope it is a number and insert in voice 1
                else:            tempo = '%d' % int (tempo)
                if s.msc.tijd == 0 and s.msr.ixm == 0: abcOut.tempo = tempo   # first measure -> header
                else: s.msr.attr += '[Q:1/4=%s]' % tempo    # otherwise -> voice
        stfnum = int (e.findtext ('staff',1))   # directions belong to a staff
        dirtyp = e.find ('direction-type')
        if dirtyp != None:
            vs = s.stfMap [stfnum][0]           # directions to first voice of staff
            t = dirtyp.find ('wedge')
            if t != None:
                type = t.get ('type')
                if   type == 'crescendo':  x = '!<(!'; s.wedge_type = '<'
                elif type == 'diminuendo': x = '!>(!'; s.wedge_type = '>'
                elif type == 'stop':
                    if s.wedge_type == '<': x = '!<)!'
                    else:                   x = '!>)!'
                else: raise Exception ('wrong wedge type')
                s.msc.appendElem (vs, x)        # to first voice
            txt = dirtyp.findtext ('words')     # insert text annotations
            if txt:
                plc = plcmnt == 'below' and '_' or '^'
                if int (e.get ('default-y', '0')) < 0: plc = '_'
                txt = txt.replace ('"','\\"').replace ('\n', ' ')
                s.msc.appendElem (vs, '"%s%s"' % (plc, txt)) # to first voice
            for key, val in dynamics_map.iteritems ():
                if dirtyp.find ('dynamics/' + key) != None:
                    s.msc.appendElem (vs, val)  # to first voice
            if dirtyp.find ('coda') != None: s.msc.appendElem (vs, 'O')
            if dirtyp.find ('segno') != None: s.msc.appendElem (vs, 'S')

    def doHarmony (s, e):   # parse a musicXMl harmony tag
        stfnum = int (e.findtext ('staff',1))   # harmony belongs to a staff
        vt = s.stfMap [stfnum][0]               # harmony to first voice of staff
        short = {'major':'', 'minor':'m', 'augmented':'+', 'diminished':'dim', 'dominant':'7', 'half-diminished':'m7b5'}
        accmap = {'major':'maj', 'dominant':'', 'minor':'m', 'diminished':'dim', 'augmented':'+', 'suspended':'sus'}
        modmap = {'second':'2', 'fourth':'4', 'seventh':'7', 'sixth':'6', 'ninth':'9', '11th':'11', '13th':'13'}
        altmap = {'1':'#', '0':'', '-1':'b'}
        root = e.findtext ('root/root-step','')
        alt = altmap.get (e.findtext ('root/root-alter'), '')
        sus = ''
        kind = e.findtext ('kind', '')
        if kind in short: kind = short [kind]
        elif '-' in kind:   # xml chord names: <triad name>-<modification>
            triad, mod = kind.split ('-')
            kind = accmap.get (triad, '') + modmap.get (mod, '')
            if kind.startswith ('sus'): kind, sus = '', kind    # sus-suffix goes to the end
        degrees = e.findall ('degree')
        for d in degrees:   # chord alterations
            kind += altmap.get (d.findtext ('degree-alter'),'') + d.findtext ('degree-value','')
        kind = kind.replace ('79','9').replace ('713','13').replace ('maj6','6')
        bass = e.findtext ('bass/bass-step','') + altmap.get (e.findtext ('bass/bass-alter'),'') 
        s.msc.appendElem (vt, '"%s%s%s%s%s"' % (root, alt, kind, sus, bass and '/' + bass))

    def doBarline (s, e):       # 0 = no repeat, 1 = begin repeat, 2 = end repeat
        rep = e.find ('repeat')
        if rep != None: rep = rep.get ('direction')
        if s.unfold:            # unfold repeat, don't translate barlines
            return rep and (rep == 'forward' and 1 or 2) or 0
        loc = e.get ('location')
        if loc == 'right':      # only change style for the right side
            style = e.findtext ('bar-style')
            if   style == 'light-light': s.msr.rline = '||'
            elif style == 'light-heavy': s.msr.rline = '|]'
        if rep != None:         # repeat found
            if rep == 'forward': s.msr.lline = ':'
            else:                s.msr.rline = ':|' # override barline style
        end = e.find ('ending')
        if end != None:
            if end.get ('type') == 'start':
                n = end.get ('number', '1').replace ('.','').replace (' ','')
                try: map (int, n.split (','))   # should be a list of integers
                except: n = '"%s"' % n.strip () # illegal musicXML
                if end.text: n = '"%s"' % end.text.strip () # text overrides numbers
                s.msr.lnum = n          # assume a start is always at the beginning of a measure
            elif s.msr.rline == '|':    # stop and discontinue the same  in ABC ?
                s.msr.rline = '||'      # to stop on a normal barline use || in ABC ?
        return 0

    def doPrint (s, e):     # print element, measure number -> insert a line break
        if e.get ('new-system') == 'yes' or e.get ('new-page') == 'yes':
            return '$'      # a line break

    def doPartList (s, e):  # translate the start/stop-event-based xml-partlist into proper tree
        for sp in e.findall ('part-list/score-part'):
            midi = {}
            for m in sp.findall ('midi-instrument'):
                x = [m.findtext (p, s.midDflt [i]) for i,p in enumerate (['midi-channel','midi-program','volume','pan'])]
                pan = float (x[3])
                if pan >= -90 and pan <= 90:    # would be better to map behind-pannings
                    pan = (float (x[3]) + 90) / 180 * 127   # xml between -90 and +90
                midi [m.get ('id')] = [int (x[0]), int (x[1]), float (x[2]), pan]
            s.instMid.append (midi)
        ps = e.find ('part-list')               # partlist  = [groupelem]
        xs = getPartlist (ps)                   # groupelem = partname | grouplist
        partlist, _ = parseParts (xs, {}, [])   # grouplist = [groupelem, ..., groupdata]
        return partlist                         # groupdata = [group-symbol, group-barline, group-name, group-abbrev]

    def mkTitle (s, e):
        def filterCredits (y):  # y == filter level, higher filters less
            cs = []
            for x in credits:   # skip redundant credit lines
                if y < 6 and (x in title or x in mvttl): continue         # sure skip
                if y < 5 and (x in composer or x in lyricist): continue   # almost sure skip
                if y < 4 and ((title and title in x) or (mvttl and mvttl in x)): continue   # may skip too much
                if y < 3 and ([1 for c in composer if c in x] or [1 for c in lyricist if c in x]): continue # skips too much
                if y < 2 and re.match (r'^[\d\W]*$', x): continue       # line only contains numbers and punctuation
                cs.append (x)
            if y == 0 and (title + mvttl): cs = ''  # default: only credit when no title set
            return cs
        title = e.findtext ('work/work-title', '')
        mvttl = e.findtext ('movement-title', '') 
        composer, lyricist, credits = [], [], []
        for creator in e.findall ('identification/creator'):
            if creator.text:
                if creator.get ('type') == 'composer':
                    composer += [line.strip () for line in creator.text.split ('\n')]
                elif creator.get ('type') in ('lyricist', 'transcriber'):
                    lyricist += [line.strip () for line in creator.text.split ('\n')]
        for credit in e.findall('credit'):
            cs = ''.join (e.text or '' for e in credit.findall('credit-words'))
            credits += [re.sub (r'\s*[\r\n]\s*', ' ', cs)]
        credits = filterCredits (s.ctf)
        if title: title = 'T:%s\n' % title
        if mvttl: title += 'T:%s\n' % mvttl
        if credits: title += '\n'.join (['T:%s' % c for c in credits]) + '\n'
        if composer: title += '\n'.join (['C:%s' % c for c in composer]) + '\n'
        if lyricist: title += '\n'.join (['Z:%s' % c for c in lyricist]) + '\n'
        if title: abcOut.title = title[:-1]

    def locStaffMap (s, part):  # map voice to staff with majority voting
        vmap = {}   # {voice -> {staff -> n}} count occurrences of voice in staff
        s.vceInst = {}          # {voice -> instrument id} for this part
        s.msc.vnums = {}        # voice id's
        ns = part.findall ('measure/note')
        for n in ns:            # count staff allocations for all notes
            v = int (n.findtext ('voice', '1'))
            s.msc.vnums [v] = 1 # collect all used voice id's in this part
            sn = int (n.findtext ('staff', '1'))
            if v not in vmap:
                vmap [v] = {sn:1}
            else:
                d = vmap[v]     # counter for voice v
                d[sn] = d.get (sn, 0) + 1   # ++ number of allocations for staff sn
            x = n.find ('instrument')
            if x != None: s.vceInst [v] = x.get ('id')
        s.stfMap, s.clefMap = {}, {}    # staff -> [voices], staff -> clef
        for v in vmap.keys ():  # choose staff with most allocations for each voice
            xs = [(n, sn) for sn, n in vmap[v].items ()]
            xs.sort ()
            stf = xs[-1][1]     # the winner: staff with most notes of voice v
            s.stfMap[stf] = s.stfMap.get (stf, []) + [v]

    def addStaffMap (s, vvmap): # vvmap: xml voice number -> global abc voice number
        part = [] # default: brace on staffs of one part
        for stf, voices in sorted (s.stfMap.items ()):  # s.stfMap has xml staff and voice numbers
            locmap = sorted ([vvmap [iv] for iv in voices if iv in vvmap])
            if locmap:          # abc voice number of staff stf
                part.append (locmap)
                clef = s.clefMap.get (stf, 'treble')    # {xml staff number -> clef}
                for iv in locmap: abcOut.clefs [iv] = clef
        s.gStfMap.append (part)

    def addMidiMap (s, ip, vvmap):      # map abc voices to midi settings
        instr = s.instMid [ip]          # get the midi settings for this part
        if instr.values (): defInstr = instr.values ()[0]   # default settings = first instrument
        else:               defInstr = s.midDflt    # no instruments defined
        xs = []
        for v, vabc in vvmap.items ():  # xml voice num, abc voice num
            id = s.vceInst.get (v, '')  # get the instrument-id for part with multiple instruments
            if id in instr:             # id is defined as midi-instrument in part-list
                   xs.append ((vabc, instr [id]))   # get midi settings for id 
            else:  xs.append ((vabc, defInstr))     # only one instrument for this part
        xs.sort ()  # put abc voices in order
        s.midiMap.extend ([midi for v, midi in xs])

    def parse (s, fobj):
        e = E.parse (fobj)
        s.mkTitle (e)
        partlist = s.doPartList (e)
        parts = e.findall ('part')
        for ip, p in enumerate (parts):
            maten = p.findall ('measure')
            s.locStaffMap (p)   # {voice -> staff} for this part
            s.msc.initVoices (newPart = 1)  # create all voices
            aantalHerhaald = 0  # keep track of number of repititions
            herhaalMaat = 0     # target measure of the repitition
            s.msr = Measure (ip)   # various measure data
            while s.msr.ixm < len (maten):
                maat = maten [s.msr.ixm]
                herhaal, lbrk = 0, ''
                s.msr.reset ()
                s.curalts = {}  # passing accidentals are reset each measure
                es = maat.getchildren ()
                for e in es:
                    if   e.tag == 'note':       s.doNote (e)
                    elif e.tag == 'attributes': s.doAttr (e)
                    elif e.tag == 'direction':  s.doDirection (e)
                    elif e.tag == 'sound':      s.doDirection (maat) # sound element directly in measure!
                    elif e.tag == 'harmony':    s.doHarmony (e)
                    elif e.tag == 'barline': herhaal = s.doBarline (e)
                    elif e.tag == 'backup':
                        dt = int (e.findtext ('duration'))
                        s.msc.incTime (-dt)
                    elif e.tag == 'forward':
                        dt = int (e.findtext ('duration'))
                        s.msc.incTime (dt)
                    elif e.tag == 'print':  lbrk = s.doPrint (e)
                s.msc.addBar (lbrk, s.msr)
                if   herhaal == 1:
                    herhaalMaat = s.msr.ixm
                    s.msr.ixm += 1
                elif herhaal == 2:
                    if aantalHerhaald < 1:  # jump
                        s.msr.ixm = herhaalMaat
                        aantalHerhaald += 1
                    else:
                        aantalHerhaald = 0  # reset
                        s.msr.ixm += 1      # just continue
                else: s.msr.ixm += 1        # on to the next measure
            vvmap = s.msc.outVoices (s.msr.divs, ip)
            s.addStaffMap (vvmap)           # update global staff map
            s.addMidiMap (ip, vvmap)
        if vvmap:
            abcOut.mkHeader (s.gStfMap, partlist, s.midiMap)
            abcOut.writeall ()
        else: info ('nothing written, %s has no notes ...' % abcOut.fnm)

#----------------
# Main Program
#----------------
if __name__ == '__main__':
    from optparse import OptionParser
    from glob import glob
    from zipfile import ZipFile 
    parser = OptionParser (usage='%prog [-h] [-u] [-m] [-c C] [-d D] [-n BPL] [-o DIR] <file1> [<file2> ...]', version=VERSION)
    parser.add_option ("-u", action="store_true", help="unfold simple repeats")
    parser.add_option ("-m", action="store_true", help="also output midi channel, volume and panning when needed")
    parser.add_option ("-c", action="store", type="int", help="set credit text filter to C", default=0, metavar='C')
    parser.add_option ("-d", action="store", type="int", help="set L:1/D", default=0, metavar='D')
    parser.add_option ("-n", action="store", type="int", help="BPL: number of bars per line", default=0, metavar='BPL')
    parser.add_option ("-o", action="store", help="store abc files in DIR", default='', metavar='DIR')
    parser.add_option ("-v", action="store", type="int", help="set volta typesetting behaviour to V", default=0, metavar='V')
    options, args = parser.parse_args ()
    if options.n < 0: parser.error ('only values >= 0')
    if options.d and options.d not in [2**n for n in range (10)]:
        parser.error ('D should be on of %s' % ','.join ([str(2**n) for n in range (10)]))
    if len (args) == 0: parser.error ('no input file given')
    pad = options.o
    if pad:
        if not os.path.exists (pad): os.mkdir (pad)
        if not os.path.isdir (pad): parser.error ('%s is not a directory' % pad)
    fnmext_list = []
    for i in args: fnmext_list += glob (i)
    if not fnmext_list: parser.error ('none of the input files exist')
    for X, fnmext in enumerate (fnmext_list):
        fnm, ext = os.path.splitext (fnmext)
        if ext.lower () not in ('.xml','.mxl'):
            info ('skipped input file %s, it should have extension .xml or .mxl' % fnmext)
            continue
        if os.path.isdir (fnmext):
            info ('skipped directory %s. Only files are accepted' % fnmext)
            continue
        if ext.lower () == '.mxl':          # extract .xml file from .mxl file
            z = ZipFile(fnmext)
            for n in z.namelist():          # assume there is always an xml file in a mxl archive !!
                if (n[:4] != 'META') and (n[-4:].lower() == '.xml'):
                    fobj = z.open (n)
                    break   # assume only one MusicXML file per archive
        else:
            fobj = open (fnmext)            # open regular xml file

        abcOut = ABCoutput (fnm + '.abc', pad, X, options.d, options.m)  # create global ABC output object
        psr = Parser (options)  # xml parser
        try:
            psr.parse (fobj)    # parse file fobj and write abc to <fnm>.abc
        except Exception, err: info ('** %s occurred: %s' % (type (err), err), 0)

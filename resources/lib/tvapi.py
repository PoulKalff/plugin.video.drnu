#
#      Copyright (C) 2014 Tommy Winther, msj33, TermeHansen
#
#  https://github.com/xbmc-danish-addons/plugin.video.drnu
#
#  This Program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2, or (at your option)
#  any later version.
#
#  This Program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with XBMC; see the file COPYING.  If not, write to
#  the Free Software Foundation, 675 Mass Ave, Cambridge, MA 02139, USA.
#  http://www.gnu.org/copyleft/gpl.html
#

import binascii
import hashlib
import json
from math import ceil
import os
from pathlib import Path
import re
import requests
import requests_cache
import struct
import urllib.parse as urlparse


class Api():
    API_URL = 'http://www.dr.dk/mu-online/api/1.2'

    def __init__(self, cachePath, getLocalizedString):
        self.cachePath = cachePath
        self.tr = getLocalizedString

        # cache expires after: 3600 = 1hour
        requests_cache.install_cache(os.path.join(
            cachePath, 'requests.cache'), backend='sqlite', expire_after=3600*8)
        requests_cache.remove_expired_responses()
        self.empty_srt = f'{self.cachePath}/{self.tr(30508)}.da.srt'

        # we need to have something in the srt to make kodi use it
        Path(self.empty_srt).write_text('1\n00:00:00,000 --> 00:01:01,000\n')

    def getLiveTV(self):
        channels = self._http_request('/channel/all-active-dr-tv-channels')
        return [channel for channel in channels if channel['Title'] in ['DR1', 'DR2', 'DR Ramasjang']]

    def getChildrenFrontItems(self, channel):
        new = f"/search/tv/programcards-latest-episode-with-asset/series-title-starts-with/?channels={channel}&orderBy=Title"
        childrenFront = self._http_request(self.API_URL + new)
        return self._handle_paging(childrenFront)

    def getThemes(self):
        themes = self._http_request('/page/tv/themes', {'themenamesonly': 'false'})
        return themes['Themes']

    def getLatestPrograms(self, channel):
        result = self._http_request('/page/tv/programs', {
            'index': '*',
            'orderBy': 'LastPrimaryBroadcastWithPublicAsset',
            'orderDescending': 'true',
            'channel': channel
        }, cache=False)
        return result['Programs']['Items']

    def getProgramIndexes(self):
        result = self._http_request('/page/tv/programs')
        if 'Indexes' in result:
            indexes = result['Indexes']
            for programIndex in indexes:
                programIndex['_Param'] = programIndex['Source'][programIndex['Source'].rindex(
                    '/') + 1:]
            return indexes
        return []

    def getAZIndexes(self):
        return [
            {'Title': 'A', '_Param': 'a'},
            {'Title': 'B', '_Param': 'b'},
            {'Title': 'C', '_Param': 'c'},
            {'Title': 'D', '_Param': 'd'},
            {'Title': 'E', '_Param': 'e'},
            {'Title': 'F', '_Param': 'f'},
            {'Title': 'G', '_Param': 'g'},
            {'Title': 'H', '_Param': 'h'},
            {'Title': 'I', '_Param': 'i'},
            {'Title': 'J', '_Param': 'j'},
            {'Title': 'K', '_Param': 'k'},
            {'Title': 'L', '_Param': 'l'},
            {'Title': 'M', '_Param': 'm'},
            {'Title': 'N', '_Param': 'n'},
            {'Title': 'O', '_Param': 'o'},
            {'Title': 'P', '_Param': 'p'},
            {'Title': 'Q', '_Param': 'q'},
            {'Title': 'R', '_Param': 'r'},
            {'Title': 'S', '_Param': 's'},
            {'Title': 'T', '_Param': 't'},
            {'Title': 'U', '_Param': 'u'},
            {'Title': 'VW', '_Param': 'v..w'},
            {'Title': 'XYZ', '_Param': 'x..z'},
            {'Title': 'ÆØÅ', '_Param': 'æ..å'},
            {'Title': '0-9', '_Param': '0..9'}
        ]

    def searchProgram(self, query, limit=75):
        # Remove various characters that makes the API puke
        cleaned_query = re.sub(r'[&()"\'\.!]', '', query)
        params = {'limit': limit}
        result = self._http_request(f'/search/tv/programcards-with-asset/title/{cleaned_query}', params=params)
        return result

    def searchSeries(self, query, startswith=False, limit=75):
        base = '/search/tv/programcards-latest-episode-with-asset/series-title'
        if startswith:
            base += '-starts-with'
        else:
            # Remove various characters that makes the API puke
            query = re.sub(r'[&()"\'\.!]', '', query)
        result = self._http_request(f'{base}/{query}', params={'limit': limit})
        return self._handle_paging(result)

    def getEpisodes(self, slug):
        result = self._http_request(f'/list/{slug}', {'limit': 75, 'expanded': True})
        return self._handle_paging(result)

    def getEpisode(self, slug):
        return self._http_request(f'/programcard/{slug}')

    def getMostViewed(self):
        result = self._http_request('/list/view/mostviewed', {'limit': 48})
        return result['Items']

    def getSelectedList(self):
        result = self._http_request('/list/view/selectedlist',
                                    {'limit': 60})
        return result['Items']

    def getVideoUrl(self, assetUri):
        result = self._http_request(assetUri)

        uri = None
        for link in result['Links']:
            if link['Target'] == 'HLS':
                uri = link['Uri']
                if uri is None:
                    uri = link['EncryptedUri']
                    uri = decrypt_uri(uri)
                break

        subtitlesUri = None
        if 'SubtitlesList' in result and len(result['SubtitlesList']) > 0:
            subtitlesUri = []
            foreign = False
            for sub in result['SubtitlesList']:
                if 'HardOfHearing' in sub['Type']:
                    name = f'{self.cachePath}/{self.tr(30506)}.da.srt'
                else:
                    foreign = True
                    name = f'{self.cachePath}/{self.tr(30507)}.da.srt'
                u = requests.get(sub['Uri'], timeout=10)
                if u.status_code != 200:
                    u.close()
                    break
                srt = self.vtt2srt(u.content)
                with open(name.encode('utf-8'), 'wb') as fh:
                    fh.write(srt.encode('utf-8'))
                u.close()
                subtitlesUri.append(name)
            if not foreign:
                # no subtitles, so probably all danish, so we need to set an empty subtitle file as first choice
                subtitlesUri = [self.empty_srt] + subtitlesUri
        return {
            'Uri': uri,
            'SubtitlesUri': subtitlesUri
        }

    def redirectImageUrl(self, imageUrl, width=300, height=170):
        # HACK: the servers behind /mu-online/api/1.2 is often returning Content-Type="text/xml"
        # instead of "image/jpeg", this problem is not pressent for /mu/bar (the "Classic API")
        assert(self.api.API_URL.endswith("/mu-online/api/1.2"))
        return imageUrl.replace("/mu-online/api/1.2/bar/", "/mu/bar/") + "?width={:d}&height={:d}".format(width, height)

    def _handle_paging(self, result):
        items = result['Items']
        while 'Next' in result['Paging']:
            result = self._http_request(result['Paging']['Next'])
            items.extend(result['Items'])
        return items

    def _http_request(self, url, params=None, cache=True):
        try:
            if not url.startswith(('http://', 'https://')):
                url = self.API_URL + urlparse.quote(url, '/')

            if params:
                url += '?' + urlparse.urlencode(params, doseq=True)

            if not cache:
                with requests_cache.disabled():
                    u = requests.get(url, timeout=30)
            else:
                u = requests.get(url, timeout=30)
            if u.status_code == 200:
                content = u.text
                u.close()
            else:
                raise ApiException(u.text)

            return json.loads(content)
        except Exception as ex:
            raise ApiException(ex)

    def vtt2srt(self, vtt):
        if isinstance(vtt, bytes):
            vtt = vtt.decode('utf-8')
        srt = vtt.replace("\r\n", "\n")
        srt = re.sub(r'([\d]+)\.([\d]+)', r'\1,\2', srt)
        srt = re.sub(r'WEBVTT\n\n', '', srt)
        srt = re.sub(r'^\d+\n', '', srt)
        srt = re.sub(r'\n\d+\n', '\n', srt)
        srt = re.sub(r'\n([\d]+)', r'\nputINDEXhere\n\1', srt)

        srtout = ['1']
        idx = 2
        for line in srt.splitlines():
            if line == 'putINDEXhere':
                line = str(idx)
                idx += 1
            srtout.append(line)
        return '\n'.join(srtout)


BLOCK_SIZE_BYTES = 16

RCON = (0x8d, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36)
SBOX = (0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
        0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0, 0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0,
        0xB7, 0xFD, 0x93, 0x26, 0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
        0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2, 0xEB, 0x27, 0xB2, 0x75,
        0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0, 0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84,
        0x53, 0xD1, 0x00, 0xED, 0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
        0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F, 0x50, 0x3C, 0x9F, 0xA8,
        0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5, 0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2,
        0xCD, 0x0C, 0x13, 0xEC, 0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
        0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14, 0xDE, 0x5E, 0x0B, 0xDB,
        0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C, 0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79,
        0xE7, 0xC8, 0x37, 0x6D, 0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
        0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F, 0x4B, 0xBD, 0x8B, 0x8A,
        0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E, 0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E,
        0xE1, 0xF8, 0x98, 0x11, 0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
        0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F, 0xB0, 0x54, 0xBB, 0x16)
SBOX_INV = (0x52, 0x09, 0x6a, 0xd5, 0x30, 0x36, 0xa5, 0x38, 0xbf, 0x40, 0xa3, 0x9e, 0x81, 0xf3, 0xd7, 0xfb,
            0x7c, 0xe3, 0x39, 0x82, 0x9b, 0x2f, 0xff, 0x87, 0x34, 0x8e, 0x43, 0x44, 0xc4, 0xde, 0xe9, 0xcb,
            0x54, 0x7b, 0x94, 0x32, 0xa6, 0xc2, 0x23, 0x3d, 0xee, 0x4c, 0x95, 0x0b, 0x42, 0xfa, 0xc3, 0x4e,
            0x08, 0x2e, 0xa1, 0x66, 0x28, 0xd9, 0x24, 0xb2, 0x76, 0x5b, 0xa2, 0x49, 0x6d, 0x8b, 0xd1, 0x25,
            0x72, 0xf8, 0xf6, 0x64, 0x86, 0x68, 0x98, 0x16, 0xd4, 0xa4, 0x5c, 0xcc, 0x5d, 0x65, 0xb6, 0x92,
            0x6c, 0x70, 0x48, 0x50, 0xfd, 0xed, 0xb9, 0xda, 0x5e, 0x15, 0x46, 0x57, 0xa7, 0x8d, 0x9d, 0x84,
            0x90, 0xd8, 0xab, 0x00, 0x8c, 0xbc, 0xd3, 0x0a, 0xf7, 0xe4, 0x58, 0x05, 0xb8, 0xb3, 0x45, 0x06,
            0xd0, 0x2c, 0x1e, 0x8f, 0xca, 0x3f, 0x0f, 0x02, 0xc1, 0xaf, 0xbd, 0x03, 0x01, 0x13, 0x8a, 0x6b,
            0x3a, 0x91, 0x11, 0x41, 0x4f, 0x67, 0xdc, 0xea, 0x97, 0xf2, 0xcf, 0xce, 0xf0, 0xb4, 0xe6, 0x73,
            0x96, 0xac, 0x74, 0x22, 0xe7, 0xad, 0x35, 0x85, 0xe2, 0xf9, 0x37, 0xe8, 0x1c, 0x75, 0xdf, 0x6e,
            0x47, 0xf1, 0x1a, 0x71, 0x1d, 0x29, 0xc5, 0x89, 0x6f, 0xb7, 0x62, 0x0e, 0xaa, 0x18, 0xbe, 0x1b,
            0xfc, 0x56, 0x3e, 0x4b, 0xc6, 0xd2, 0x79, 0x20, 0x9a, 0xdb, 0xc0, 0xfe, 0x78, 0xcd, 0x5a, 0xf4,
            0x1f, 0xdd, 0xa8, 0x33, 0x88, 0x07, 0xc7, 0x31, 0xb1, 0x12, 0x10, 0x59, 0x27, 0x80, 0xec, 0x5f,
            0x60, 0x51, 0x7f, 0xa9, 0x19, 0xb5, 0x4a, 0x0d, 0x2d, 0xe5, 0x7a, 0x9f, 0x93, 0xc9, 0x9c, 0xef,
            0xa0, 0xe0, 0x3b, 0x4d, 0xae, 0x2a, 0xf5, 0xb0, 0xc8, 0xeb, 0xbb, 0x3c, 0x83, 0x53, 0x99, 0x61,
            0x17, 0x2b, 0x04, 0x7e, 0xba, 0x77, 0xd6, 0x26, 0xe1, 0x69, 0x14, 0x63, 0x55, 0x21, 0x0c, 0x7d)
MIX_COLUMN_MATRIX = ((0x2, 0x3, 0x1, 0x1),
                     (0x1, 0x2, 0x3, 0x1),
                     (0x1, 0x1, 0x2, 0x3),
                     (0x3, 0x1, 0x1, 0x2))
MIX_COLUMN_MATRIX_INV = ((0xE, 0xB, 0xD, 0x9),
                         (0x9, 0xE, 0xB, 0xD),
                         (0xD, 0x9, 0xE, 0xB),
                         (0xB, 0xD, 0x9, 0xE))
RIJNDAEL_EXP_TABLE = (0x01, 0x03, 0x05, 0x0F, 0x11, 0x33, 0x55, 0xFF, 0x1A, 0x2E, 0x72, 0x96, 0xA1, 0xF8, 0x13, 0x35,
                      0x5F, 0xE1, 0x38, 0x48, 0xD8, 0x73, 0x95, 0xA4, 0xF7, 0x02, 0x06, 0x0A, 0x1E, 0x22, 0x66, 0xAA,
                      0xE5, 0x34, 0x5C, 0xE4, 0x37, 0x59, 0xEB, 0x26, 0x6A, 0xBE, 0xD9, 0x70, 0x90, 0xAB, 0xE6, 0x31,
                      0x53, 0xF5, 0x04, 0x0C, 0x14, 0x3C, 0x44, 0xCC, 0x4F, 0xD1, 0x68, 0xB8, 0xD3, 0x6E, 0xB2, 0xCD,
                      0x4C, 0xD4, 0x67, 0xA9, 0xE0, 0x3B, 0x4D, 0xD7, 0x62, 0xA6, 0xF1, 0x08, 0x18, 0x28, 0x78, 0x88,
                      0x83, 0x9E, 0xB9, 0xD0, 0x6B, 0xBD, 0xDC, 0x7F, 0x81, 0x98, 0xB3, 0xCE, 0x49, 0xDB, 0x76, 0x9A,
                      0xB5, 0xC4, 0x57, 0xF9, 0x10, 0x30, 0x50, 0xF0, 0x0B, 0x1D, 0x27, 0x69, 0xBB, 0xD6, 0x61, 0xA3,
                      0xFE, 0x19, 0x2B, 0x7D, 0x87, 0x92, 0xAD, 0xEC, 0x2F, 0x71, 0x93, 0xAE, 0xE9, 0x20, 0x60, 0xA0,
                      0xFB, 0x16, 0x3A, 0x4E, 0xD2, 0x6D, 0xB7, 0xC2, 0x5D, 0xE7, 0x32, 0x56, 0xFA, 0x15, 0x3F, 0x41,
                      0xC3, 0x5E, 0xE2, 0x3D, 0x47, 0xC9, 0x40, 0xC0, 0x5B, 0xED, 0x2C, 0x74, 0x9C, 0xBF, 0xDA, 0x75,
                      0x9F, 0xBA, 0xD5, 0x64, 0xAC, 0xEF, 0x2A, 0x7E, 0x82, 0x9D, 0xBC, 0xDF, 0x7A, 0x8E, 0x89, 0x80,
                      0x9B, 0xB6, 0xC1, 0x58, 0xE8, 0x23, 0x65, 0xAF, 0xEA, 0x25, 0x6F, 0xB1, 0xC8, 0x43, 0xC5, 0x54,
                      0xFC, 0x1F, 0x21, 0x63, 0xA5, 0xF4, 0x07, 0x09, 0x1B, 0x2D, 0x77, 0x99, 0xB0, 0xCB, 0x46, 0xCA,
                      0x45, 0xCF, 0x4A, 0xDE, 0x79, 0x8B, 0x86, 0x91, 0xA8, 0xE3, 0x3E, 0x42, 0xC6, 0x51, 0xF3, 0x0E,
                      0x12, 0x36, 0x5A, 0xEE, 0x29, 0x7B, 0x8D, 0x8C, 0x8F, 0x8A, 0x85, 0x94, 0xA7, 0xF2, 0x0D, 0x17,
                      0x39, 0x4B, 0xDD, 0x7C, 0x84, 0x97, 0xA2, 0xFD, 0x1C, 0x24, 0x6C, 0xB4, 0xC7, 0x52, 0xF6, 0x01)
RIJNDAEL_LOG_TABLE = (0x00, 0x00, 0x19, 0x01, 0x32, 0x02, 0x1a, 0xc6, 0x4b, 0xc7, 0x1b, 0x68, 0x33, 0xee, 0xdf, 0x03,
                      0x64, 0x04, 0xe0, 0x0e, 0x34, 0x8d, 0x81, 0xef, 0x4c, 0x71, 0x08, 0xc8, 0xf8, 0x69, 0x1c, 0xc1,
                      0x7d, 0xc2, 0x1d, 0xb5, 0xf9, 0xb9, 0x27, 0x6a, 0x4d, 0xe4, 0xa6, 0x72, 0x9a, 0xc9, 0x09, 0x78,
                      0x65, 0x2f, 0x8a, 0x05, 0x21, 0x0f, 0xe1, 0x24, 0x12, 0xf0, 0x82, 0x45, 0x35, 0x93, 0xda, 0x8e,
                      0x96, 0x8f, 0xdb, 0xbd, 0x36, 0xd0, 0xce, 0x94, 0x13, 0x5c, 0xd2, 0xf1, 0x40, 0x46, 0x83, 0x38,
                      0x66, 0xdd, 0xfd, 0x30, 0xbf, 0x06, 0x8b, 0x62, 0xb3, 0x25, 0xe2, 0x98, 0x22, 0x88, 0x91, 0x10,
                      0x7e, 0x6e, 0x48, 0xc3, 0xa3, 0xb6, 0x1e, 0x42, 0x3a, 0x6b, 0x28, 0x54, 0xfa, 0x85, 0x3d, 0xba,
                      0x2b, 0x79, 0x0a, 0x15, 0x9b, 0x9f, 0x5e, 0xca, 0x4e, 0xd4, 0xac, 0xe5, 0xf3, 0x73, 0xa7, 0x57,
                      0xaf, 0x58, 0xa8, 0x50, 0xf4, 0xea, 0xd6, 0x74, 0x4f, 0xae, 0xe9, 0xd5, 0xe7, 0xe6, 0xad, 0xe8,
                      0x2c, 0xd7, 0x75, 0x7a, 0xeb, 0x16, 0x0b, 0xf5, 0x59, 0xcb, 0x5f, 0xb0, 0x9c, 0xa9, 0x51, 0xa0,
                      0x7f, 0x0c, 0xf6, 0x6f, 0x17, 0xc4, 0x49, 0xec, 0xd8, 0x43, 0x1f, 0x2d, 0xa4, 0x76, 0x7b, 0xb7,
                      0xcc, 0xbb, 0x3e, 0x5a, 0xfb, 0x60, 0xb1, 0x86, 0x3b, 0x52, 0xa1, 0x6c, 0xaa, 0x55, 0x29, 0x9d,
                      0x97, 0xb2, 0x87, 0x90, 0x61, 0xbe, 0xdc, 0xfc, 0xbc, 0x95, 0xcf, 0xcd, 0x37, 0x3f, 0x5b, 0xd1,
                      0x53, 0x39, 0x84, 0x3c, 0x41, 0xa2, 0x6d, 0x47, 0x14, 0x2a, 0x9e, 0x5d, 0x56, 0xf2, 0xd3, 0xab,
                      0x44, 0x11, 0x92, 0xd9, 0x23, 0x20, 0x2e, 0x89, 0xb4, 0x7c, 0xb8, 0x26, 0x77, 0x99, 0xe3, 0xa5,
                      0x67, 0x4a, 0xed, 0xde, 0xc5, 0x31, 0xfe, 0x18, 0x0d, 0x63, 0x8c, 0x80, 0xc0, 0xf7, 0x70, 0x07)


def compat_struct_pack(spec, *args):
    if isinstance(spec, str):
        spec = spec.encode('ascii')
    return struct.pack(spec, *args)


def compat_struct_unpack(spec, *args):
    if isinstance(spec, str):
        spec = spec.encode('ascii')
    return struct.unpack(spec, *args)


def mix_column(data, matrix):
    data_mixed = []
    for row in range(4):
        mixed = 0
        for column in range(4):
            # xor is (+) and (-)
            mixed ^= rijndael_mul(data[column], matrix[row][column])
        data_mixed.append(mixed)
    return data_mixed


def mix_columns(data, matrix=MIX_COLUMN_MATRIX):
    data_mixed = []
    for i in range(4):
        column = data[i * 4: (i + 1) * 4]
        data_mixed += mix_column(column, matrix)
    return data_mixed


def mix_columns_inv(data):
    return mix_columns(data, MIX_COLUMN_MATRIX_INV)


def rijndael_mul(a, b):
    if(a == 0 or b == 0):
        return 0
    return RIJNDAEL_EXP_TABLE[(RIJNDAEL_LOG_TABLE[a] + RIJNDAEL_LOG_TABLE[b]) % 0xFF]


def shift_rows_inv(data):
    data_shifted = []
    for column in range(4):
        for row in range(4):
            data_shifted.append(data[((column - row) & 0b11) * 4 + row])
    return data_shifted


def sub_bytes(data):
    return [SBOX[x] for x in data]


def sub_bytes_inv(data):
    return [SBOX_INV[x] for x in data]


def rotate(data):
    return data[1:] + [data[0]]


def key_schedule_core(data, rcon_iteration):
    data = rotate(data)
    data = sub_bytes(data)
    data[0] = data[0] ^ RCON[rcon_iteration]

    return data


def xor(data1, data2):
    return [x ^ y for x, y in zip(data1, data2)]


def key_expansion(data):
    """
    Generate key schedule
    @param {int[]} data  16/24/32-Byte cipher key
    @returns {int[]}     176/208/240-Byte expanded key
    """
    data = data[:]  # copy
    rcon_iteration = 1
    key_size_bytes = len(data)
    expanded_key_size_bytes = (key_size_bytes // 4 + 7) * BLOCK_SIZE_BYTES

    while len(data) < expanded_key_size_bytes:
        temp = data[-4:]
        temp = key_schedule_core(temp, rcon_iteration)
        rcon_iteration += 1
        data += xor(temp, data[-key_size_bytes: 4 - key_size_bytes])

        for _ in range(3):
            temp = data[-4:]
            data += xor(temp, data[-key_size_bytes: 4 - key_size_bytes])

        if key_size_bytes == 32:
            temp = data[-4:]
            temp = sub_bytes(temp)
            data += xor(temp, data[-key_size_bytes: 4 - key_size_bytes])

        for _ in range(3 if key_size_bytes == 32 else 2 if key_size_bytes == 24 else 0):
            temp = data[-4:]
            data += xor(temp, data[-key_size_bytes: 4 - key_size_bytes])
    data = data[:expanded_key_size_bytes]

    return data


def aes_decrypt(data, expanded_key):
    """
    Decrypt one block with aes
    @param {int[]} data          16-Byte cipher
    @param {int[]} expanded_key  176/208/240-Byte expanded key
    @returns {int[]}             16-Byte state
    """
    rounds = len(expanded_key) // BLOCK_SIZE_BYTES - 1

    for i in range(rounds, 0, -1):
        data = xor(data, expanded_key[i * BLOCK_SIZE_BYTES: (i + 1) * BLOCK_SIZE_BYTES])
        if i != rounds:
            data = mix_columns_inv(data)
        data = shift_rows_inv(data)
        data = sub_bytes_inv(data)
    data = xor(data, expanded_key[:BLOCK_SIZE_BYTES])

    return data


def bytes_to_intlist(bs):
    if not bs:
        return []
    if isinstance(bs[0], int):  # Python 3
        return list(bs)
    else:
        return [ord(c) for c in bs]


def intlist_to_bytes(xs):
    if not xs:
        return b''
    return compat_struct_pack('%dB' % len(xs), *xs)


def hex_to_bytes(hex):
    return binascii.a2b_hex(hex.encode('ascii'))


def aes_cbc_decrypt(data, key, iv):
    """
    Decrypt with aes in CBC mode
    @param {int[]} data        cipher
    @param {int[]} key         16/24/32-Byte cipher key
    @param {int[]} iv          16-Byte IV
    @returns {int[]}           decrypted data
    """
    expanded_key = key_expansion(key)
    block_count = int(ceil(float(len(data)) / BLOCK_SIZE_BYTES))

    decrypted_data = []
    previous_cipher_block = iv
    for i in range(block_count):
        block = data[i * BLOCK_SIZE_BYTES: (i + 1) * BLOCK_SIZE_BYTES]
        block += [0] * (BLOCK_SIZE_BYTES - len(block))

        decrypted_block = aes_decrypt(block, expanded_key)
        decrypted_data += xor(decrypted_block, previous_cipher_block)
        previous_cipher_block = block
    decrypted_data = decrypted_data[:len(data)]

    return decrypted_data


def decrypt_uri(e):
    n = int(e[2:10], 16)
    a = e[10 + n:]
    data = bytes_to_intlist(hex_to_bytes(e[10:10 + n]))
    key = bytes_to_intlist(hashlib.sha256(
        ('%s:sRBzYNXBzkKgnjj8pGtkACch' % a).encode('utf-8')).digest())
    iv = bytes_to_intlist(hex_to_bytes(a))
    decrypted = aes_cbc_decrypt(data, key, iv)
    return intlist_to_bytes(
        decrypted[:-decrypted[-1]]).decode('utf-8').split('?')[0]


class ApiException(Exception):
    pass

# -*- coding:utf-8 -*-
import re
import json
import tools
from tools import XMLUtils

# 获取url所需请求头
def getHeaders(url):
    isBilibili = url.find('acgvideo.com') > 0 or url.find('bili') > 0
    isIqiyi = url.find('iqiyi.com') > 0
    isMgtv = url.find('mgtv.com') > 0

    headers = {}

    if isBilibili:
        headers['referer'] = 'https://www.bilibili.com/'
    elif isIqiyi:
        headers['referer'] = 'https://www.iqiyi.com/'
    elif isMgtv:
        headers['referer'] = 'https://www.mgtv.com/'
    return headers

# iqiyi: 解析mpd文件
def parseIqiyiMpd(content, headers = {}):
    mediaUrls = {
        'audio': [],
        'video': [],
    }
    root = XMLUtils.parse(content)
    items = XMLUtils.findall(root, 'Period/AdaptationSet/Representation')

    for item in items:
        mType = item.attrib['mimeType'].split('/')[0]
        segName = XMLUtils.findtext(item, 'BaseURL')
        clipItems = XMLUtils.findall(root, "clip_list/clip[BaseURL='%s']" % segName)

        for clip in clipItems:
            infoUrl = XMLUtils.findtext(clip, 'remote_path').replace('&amp;', '&')
            mediaInfo = json.loads(tools.getText(infoUrl, headers))
            mediaUrls[mType].append(mediaInfo['l'])

    return mediaUrls['audio'], mediaUrls['video']

def parseHls(url, headers = {}):
    content = tools.getText(url, headers)
    return tools.filterHlsUrls(content, url)

def parseIqiyiUrl(url, headers = {}):
    data = json.loads(tools.getText(url, headers))
    videos = data['data']['program']['video']
    videos = list(filter(lambda each: each.get('m3u8'), videos))
    content = videos[0]['m3u8']

    if content.startswith('#EXTM3U'):
        videoType = 'hls'
        audioUrls, videoUrls = [], tools.filterHlsUrls(content)
    else:
        videoType = 'dash'
        audioUrls, videoUrls = parseIqiyiMpd(content, headers)
    return videoType, audioUrls, videoUrls

# 预处理油猴链接，返回解析后的url和所需请求头
def preProcessUrl(url):
    isBilibili = url.find('acgvideo.com') > 0 or url.find('bili') > 0
    isIqiyi = url.find('iqiyi.com') > 0

    headers = getHeaders(url)
    urls = url.split('|')
    videoType = ''
    audioUrls = []
    videoUrls = []

    if url.find('.m3u8') > 0:
        videoType = 'hls'
        videoUrls = parseHls(url, headers)
    elif isBilibili and url.find('.m4s') > 0:
        videoType = 'dash'
        audioUrls, videoUrls = urls[:1], urls[1:]
    elif isIqiyi:
        videoType, audioUrls, videoUrls = parseIqiyiUrl(url, headers)
    else:
        videoType = 'partial'
        videoUrls = urls

    return videoType, headers, audioUrls, videoUrls


# bilibili: 获取所有分P信息
def getAllPartInfo(url):
    content = tools.getText(url, getHeaders(url))

    # 获取分p名称和cid
    match = re.search(r'<script>window\.__INITIAL_STATE__=(.+?});.+?</script>', content)
    data = json.loads(match.group(1))
    isOpera = 'epList' in data
    pages = data['epList'] if isOpera else data['videoData']['pages']

    allPartInfo = []
    for page in pages:
        if isOpera:
            name, partUrl = page['longTitle'], re.sub(r'\d+$', str(page['id']), url)
        else:
            name, partUrl = page['part'], url + '?p=' + str(page['page'])
        allPartInfo.append({
            'cid': page['cid'],
            'name': name,
            'url': partUrl,
        })

    return allPartInfo

# bilibili: 获取指定p的视频url
def getPartUrl(partUrl, partCid, basePlayInfoUrl, sessCookie):
    def sortBandWidth(item):
        return item['id'] * (10**10) + item['bandwidth']

    headers = getHeaders(partUrl)
    headers['Cookie'] = "CURRENT_FNVAL=16"
    content = tools.getText(partUrl, headers)

    match = re.search(r'<script>window\.__playinfo__=(.+?)</script>', content)

    if match: 
        data = match.group(1)
        data = json.loads(data)['data']
    else: 
        playInfoUrl = basePlayInfoUrl + '&cid=' + str(partCid)
        headers = { 'Cookie': sessCookie }
        data = json.loads(tools.getText(playInfoUrl, headers))
        data = data.get('data', None) or data.get('result', None)

    if 'dash' in data:
        # 音视频分离
        data = data['dash']
        data['audio'].sort(key=sortBandWidth, reverse=True)
        data['video'].sort(key=sortBandWidth, reverse=True)
        combineVideoUrl = data['audio'][0]['baseUrl'] + '|' + data['video'][0]['baseUrl']
    elif 'durl' in data:
        # 视频分段
        data = data['durl']
        urls = list(map(lambda each: each['url'], data))
        combineVideoUrl = '|'.join(urls)

    return combineVideoUrl

# bilibili: 预处理多p油猴链接
def preProcessMultiPartUrl(url, pRange):
    if url.find('|') != -1:
        baseUrl, basePlayInfoUrl, sessCookie = url.split('|')
    else:
        baseUrl, basePlayInfoUrl, sessCookie = url, '', ''

    baseUrl = baseUrl.split('?')[0]
    pRange = pRange.split(' ')
    startP = int(pRange[0])
    endP = int(pRange[1]) if len(pRange) > 1 else startP

    allPartInfo = getAllPartInfo(baseUrl)
    for i in range(startP - 1, endP):
        partInfo = allPartInfo[i]
        partUrl, partCid = partInfo['url'], partInfo['cid']
        combineVideoUrl = getPartUrl(partUrl, partCid, basePlayInfoUrl, sessCookie)
        partInfo['videoUrl'] = combineVideoUrl

    return startP, endP, allPartInfo
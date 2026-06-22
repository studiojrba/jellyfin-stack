#!/usr/bin/env python3
import re
P="/cfg/root/default/Anime/options.xml"
s=open(P,encoding="utf-8").read()
old="""    <TypeOptions>
      <Type>Episode</Type>
      <MetadataFetchers>
        <string>One Pace</string>
        <string>AniDB</string>
      </MetadataFetchers>
      <MetadataFetcherOrder>
        <string>One Pace</string>
        <string>AniDB</string>
        <string>TheTVDB</string>
        <string>TheMovieDb</string>
        <string>The Open Movie Database</string>
      </MetadataFetcherOrder>
      <ImageFetchers>
        <string>One Pace</string>
        <string>TheTVDB</string>
        <string>TheMovieDb</string>
        <string>The Open Movie Database</string>
        <string>Embedded Image Extractor</string>
        <string>Screen Grabber</string>
      </ImageFetchers>
      <ImageFetcherOrder>
        <string>One Pace</string>
        <string>TheTVDB</string>
        <string>TheMovieDb</string>
        <string>The Open Movie Database</string>
        <string>Embedded Image Extractor</string>
        <string>Screen Grabber</string>
      </ImageFetcherOrder>
      <ImageOptions />
    </TypeOptions>"""
new="""    <TypeOptions>
      <Type>Episode</Type>
      <MetadataFetchers>
        <string>AniDB</string>
      </MetadataFetchers>
      <MetadataFetcherOrder>
        <string>AniDB</string>
        <string>TheTVDB</string>
        <string>TheMovieDb</string>
        <string>The Open Movie Database</string>
      </MetadataFetcherOrder>
      <ImageFetchers>
        <string>TheTVDB</string>
        <string>TheMovieDb</string>
        <string>The Open Movie Database</string>
      </ImageFetchers>
      <ImageFetcherOrder>
        <string>TheTVDB</string>
        <string>TheMovieDb</string>
        <string>The Open Movie Database</string>
      </ImageFetcherOrder>
      <ImageOptions />
    </TypeOptions>"""
if old in s:
    s=s.replace(old,new)
    open(P,"w",encoding="utf-8").write(s)
    print("options.xml updated: removed One Pace + Screen Grabber from Episode fetchers")
else:
    print("PATTERN NOT FOUND - no change")

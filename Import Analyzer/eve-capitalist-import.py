# EVE Capitalist Import Analyzer 0.1
# EVE Capitalist - Market information analyzer for EVE Online
# Copyright (C) 2018  Magane Concordia

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import requests
import aiohttp
import asyncio
import json
import csv
import time

# Define constants
# Base URL
BaseUrl = 'https://esi.evetech.net/latest/'

# API URLs
SearchUrl = BaseUrl+'search/'
MarketUrl = BaseUrl+'markets/'
UniverseUrl = BaseUrl+'universe/'

# Courier fees per volume
CourierFee = 750

# Query Constraints
# Case sensitive. Change this to the region you would like to check.
regionName = 'Delve'
refRegionId = 10000002  # The Forge
# Minimum percentage price difference to be shortlisted. 0.2 = 20% difference
minDeltaPrice = 0.20

# Concurrency Limit
conLimit = 200  # 200 is recommended for unstable internet

# Time Keeping
startTime = time.time()

# If we want to load existing price databases
loadExisting = False

# Filter items that only sold for 1 unit
removeSmallVolume = True
#########################################################################################
# Get region ID
payload = {'categories': ['region'], 'search': regionName, 'strict': 'true'}
r = requests.get(SearchUrl, params=payload)
regionId = r.json()['region'][0]

# For each relevant type, get their prices at reference location and at queried location
# Use history API because CCPls don't show prices at structures
refDict = dict()
queryDict = dict()
infoDict = dict()

# Async functions for gathering data from ESI
async def getPriceHistory(historyDict, typeIds, regionId, session):
    endpoint = str(regionId)+'/history/'
    url = MarketUrl + endpoint
    for typeId in typeIds:
        params = {'type_id': typeId}
        async with session.get(url, params=params) as r:
            try:
                data = await r.json()
                prices = data[len(data)-1]
                historyDict[typeId] = prices
            except:
                print(
                    'Error for type %i: market data unavailable.' % typeId)


async def getInfo(infoDict, typeIds, session):
    for typeId in typeIds:
        endpoint = 'types/' + str(typeId)
        url = UniverseUrl + endpoint
        async with session.get(url) as r:
            try:
                data = await r.json()
                name = data['name']
                volume = data['packaged_volume']
                infoDict[typeId] = {'name': name, 'volume': volume}
            except:
                print('Error for type %i: failed to fetch information.' % typeId)

# Initialise Connections
loop = asyncio.get_event_loop()
conn = aiohttp.TCPConnector(limit=conLimit)
session = aiohttp.ClientSession(connector=conn, loop=loop)

# Get data from ESI/local file
if not(loadExisting):
    # Get types relevant to the region
    print('Getting relevant item types:')
    relevantTypes = []
    i = 1
    while(True):
        if i % 3 == 0:
            print('Processing Page %i' % i)
        r = requests.get(MarketUrl+str(regionId)+'/types/', params={'page': i})
        data = r.json()
        if data == []:
            break
        else:
            relevantTypes += data  # Array of relevant types
            i += 1
    relevantTypes = list(set(relevantTypes))  # Remove duplicate types

    # For Testing Concurrency Limits
    # r = requests.get(MarketUrl+str(regionId)+'/types/', params={'page': i})
    # data = r.json()
    # relevantTypes += data

    print('Getting local prices for %i types...' % len(relevantTypes))
    loop.run_until_complete(getPriceHistory(
        queryDict, relevantTypes, regionId, session))

    # Save local price database
    with open('queryPrices.json', 'w') as f:
        json.dump(queryDict, f)
    relevantTypes = list(queryDict)  # Some types may not be available
    print('Getting reference prices for %i types...' % len(relevantTypes))
    loop.run_until_complete(getPriceHistory(
        refDict, relevantTypes, refRegionId, session))
    print('CCPls has granted us the prices')
    # Store database for reference prices
    with open('refPrices.json', 'w') as f:
        json.dump(refDict, f)
# Load databases
else:
    print('Loading existing price databases...')
    with open('queryPrices.json', 'r') as fp:
        queryDict = json.load(fp)
    with open('refPrices.json', 'r') as fp:
        refDict = json.load(fp)
    print('Databases sucessfully loaded')
    relevantTypes = list(queryDict)  # Some types may not be available

# Compare price percentages
print('Calculating prices differences...')
for typeId in relevantTypes:
    try:
        refP = refDict[typeId]['average']
        queryP = queryDict[typeId]['average']
        delta = queryP-refP
        deltaPer = delta/refP
        # Remove entries under threshold
        if deltaPer <= minDeltaPrice:
            del queryDict[typeId]
        # Remove those listings with volume == 1
        else:
            if (queryDict[typeId]['volume'] == 1) and removeSmallVolume:
                del queryDict[typeId]
    except:
        del queryDict[typeId] # Reference prices not available


# Get info for those types
relevantTypes = list(queryDict)
print('Getting information for %i short-listed types...' % len(relevantTypes))
loop.run_until_complete(
    getInfo(infoDict, relevantTypes, session)
)

# Calculate courier fee and compare price percentages
print('Calculating courier fee...')
deltaList = []
for typeId in relevantTypes:
    refP = refDict[typeId]['average']
    queryP = queryDict[typeId]['average']
    extraFee = CourierFee * infoDict[typeId]['volume']
    delta = queryP-extraFee-refP
    deltaPer = delta/refP
    # Remove entries under threshold
    if deltaPer > minDeltaPrice:
        deltaList.append((typeId, deltaPer, delta))

print('Finished. %i types in final list with higher than %.1f percent markup.' %
      (len(deltaList), 100*minDeltaPrice))

# Calculate import profits
profitsList = []
for entry in deltaList:
    typeId = entry[0]
    queryP = queryDict[typeId]['average']
    typeName = infoDict[typeId]['name']
    tradeVolume = queryDict[typeId]['volume']
    itemVolume = infoDict[typeId]['volume']
    profit = tradeVolume*entry[2]
    profitsList.append([typeName, queryP, entry[1], entry[2],
                        tradeVolume, profit, itemVolume])

# Sort the list
profitsList = sorted(profitsList, key=lambda element: element[5], reverse=True)

# Print and output the results
print('Writing Results to EVE Capitalist Import Report - %s.csv...' % regionName )
with open('EVE Capitalist Import Report - %s.csv' % regionName, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['Type', 'Average Price', 'Price Difference (%)', 'Price Difference Per Unit',
                     'Trade Volume', 'Profit',  'Volume Per Unit'])
    writer.writerows(profitsList)

# Close sessions
conn.close()
loop.close()

# Clean up and report
elapsedTime = time.time()-startTime
print('Computation finished in %f seconds' % elapsedTime)

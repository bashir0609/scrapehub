scraper name: ads.txt checker

scraper description: 
I need to check ads.txt files of websites. website url is in the input file. website url many need to cleaned before checking.
ads.txt file url is website url + /ads.txt
app-ads.txt file url is website url + /app-ads.txt

we may need to fix ssl, non ssl, www, non www, redirect, etc. before checking.

workflow:
1. read website url from input file
2. clean website url
3. check website url is valid
4. detect homepage url
5. check ads.txt file
6. check app-ads.txt file
7. write result to output file


Result columns:
website url
ads.txt URL
ads.txt URL Status Code
ads.txt URL Result Text
ads.txt URL Content when status code is 200
ads.txt URL Content contains html tag? yes/no
ads.txt URL Time (ms)

app-ads.txt URL
app-ads.txt URL Status Code
app-ads.txt URL Result Text
app-ads.txt URL Content when status code is 200
app-ads.txt URL Content contains html tag? yes/no
app-ads.txt URL Time (ms)


Other features:
live job progress
pagination in result view
csv file upload
result file download contains upload file name
result file download contains uploaded file data and result data
domain column selection when csv file upload
stats of status code (total, success, error, etc.) seprate stats for ads.txt and app-ads.txt
estimated time to finish
job pause and resume
job stop
job auto pause when server down
job auto resume when server up

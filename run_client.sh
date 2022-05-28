#!/bin/sh
for i in  0 1 
do
   python ./client_app.py -id $i -nm 10 & 
done

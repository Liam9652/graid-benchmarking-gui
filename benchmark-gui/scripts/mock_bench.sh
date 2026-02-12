#!/bin/bash
LOG_FILE="./mock_output.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "Normal output line 1"
echo "STATUS: ERROR: Mock Error Message"
echo "Normal output line 2"
exit 1

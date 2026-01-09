
import pandas as pd
import time
from pathlib import Path
import shutil
import os
import sys
import re




def preprocess_iostat_files(directory):
    # Convert to pathlib.Path object if not already one
    directory = Path(directory)

    # Iterate over all files in the directory
    for file_path in directory.iterdir():
        if file_path.is_file():  # Check if it's a file (not a subdirectory)
            # Replace underscores with dashes in the filename
            new_file_path = file_path.with_name(
                file_path.name.replace("_", "-"))
            # print(new_file_path)
            shutil.move(str(file_path), str(new_file_path))  # Rename the file


def delete_folder(pth):
    for sub in pth.iterdir():
        if sub.is_dir():
            delete_folder(sub)
        else:
            sub.unlink()
    pth.rmdir()


def rm_folder(u_file_path, query_id):
    try:
        result_file_lst = [x for x in Path(
            u_file_path).rglob('*') if x.is_dir() and x.stem == query_id]

        for sub in result_file_lst:
            delete_folder(Path(sub))
    except:
        pass


def set_dataframe(u_df, u_filepath):
    integer_number_of_rows = len(u_df)
    data = parser_filename(u_filepath)
    # df = pd.DataFrame(
    #     data, columns=['SSD', 'RAID_status', 'RAID_type', 'PD_count', 'stage'])
    df = pd.DataFrame({
        "Model": [data[-1]]*integer_number_of_rows,
        "SSD": [data[0]]*integer_number_of_rows,
        "RAID_status": [data[1]]*integer_number_of_rows,
        "RAID_type": [data[2]]*integer_number_of_rows,
        "PD_count": [data[3]]*integer_number_of_rows,
        "stage": [data[4]]*integer_number_of_rows,
        "Ben_type": [data[5]]*integer_number_of_rows,
        "controller": [data[-2]]*integer_number_of_rows,
        "WriteCache": [data[-3]]*integer_number_of_rows,
        "Tasks_number": [data[-4]]*integer_number_of_rows,

    })
    # filename_lst = [device, status, RAID_type,
    #                 PD_count, stage, fio_type,  Jobs, wt, controller, model]
    #print(df)

    return df


def create_folder(u_folder, u_floder_name: str):

    u_floder_name = Path(Path(u_folder).parent).joinpath(u_floder_name)
    try:
        u_floder_name.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        #print("Folder is already there")
        pass

    else:
        #print("Folder was created")
        pass
    return u_floder_name


def parser_diskspd(u_file_path):
    # path = '/Users/liam/Downloads/a2000/disksdp/normal/ntfs/graid-a2000-ntfs-1vd-randread-j32b4kd32.txt'

    with open(u_file_path) as f:
        lines = f.readlines()
        list_BW_iops = []
        for line in lines:
            if "total" in line:
                result = [x.strip() for x in line.split('|')]
                # print(result)
                list_BW_iops.append(result)
            if "Command Line" in line:
                command = [line.split(" ")[3][2:], line.split(" ")[
                    4][2:], line.split(" ")[5][2:]]
                if (int(line.split(" ")[6][2:]) == 0 and (line.split(" ")[12][1:]) == "r"):
                    command.append('RandromRead')
                elif (int(line.split(" ")[6][2:]) == 100 and (line.split(" ")[12][1:]) == "r"):
                    command.append('RandromWirte')
                elif (int(line.split(" ")[6][2:]) == 30 and (line.split(" ")[12][1:]) == "r"):
                    command.append('RandromRW70')
                elif (int(line.split(" ")[6][2:]) == 0 and (line.split(" ")[12][1:]) == "si"):
                    command.append('SequentialRead')
                elif (int(line.split(" ")[6][2:]) == 100 and (line.split(" ")[12][1:]) == "si"):
                    command.append('SequentialWrite')
        # list_BW_iops[1][0]
        for i in range(len(list_BW_iops)):
            result = [x.strip() for x in list_BW_iops[i][0].split(':')]
            list_BW_iops[i][0] = result[1]
        list_BW_iops_n = []
        for i in range(len(list_BW_iops)):
            list_BW_iops_n.append([sub.replace('N/A', '0')
                                   for sub in list_BW_iops[i]])

        # print(line.split(' | '))

    result_folder = create_folder(u_file_path, 'result')
    file_name_parser = Path(u_file_path).stem.split('-')
    if 'recovery' in file_name_parser:
        raid_status = 'Rebuild'
    elif 'resync' in file_name_parser:
        raid_status = 'Resync'
    else:
        raid_status = 'Normal'

    data_info = [
        Path(u_file_path).stem,
        'diskspd',
        command[3],
        raid_status,
        file_name_parser[3][0],
        9,
        'RAID5',
        file_name_parser[2],
        command[0],
        command[1],
        command[2],
        float(list_BW_iops_n[0][2])/1024,
        float(list_BW_iops_n[0][3])/1000,
        float(list_BW_iops_n[0][4]),
        float(list_BW_iops_n[0][6]),
        float(list_BW_iops_n[1][2])/1024,
        float(list_BW_iops_n[1][3])/1000,
        float(list_BW_iops_n[1][4]),
        float(list_BW_iops_n[1][6]),
        float(list_BW_iops_n[2][2])/1024,
        float(list_BW_iops_n[2][3])/1000,
        float(list_BW_iops_n[2][4]),
        float(list_BW_iops_n[2][6]),
    ]
    df = pd.DataFrame(data_info).transpose()
    result_file = Path(result_folder).joinpath(''.join(
        [Path(u_file_path).stem, '_',  time.strftime("%Y%m%d_%H%M"), '_diskspd', '.csv']))
    # print(result_file)
    # print((df_t.keys().tolist()))
    # print(len(header))

    header = [
        'file_name',
        'Tool',
        'type',
        'Status',
        'VD count',
        'PD count',
        'RAID type',
        'FileSystem',
        'Total Thread',
        'Depth',
        'blocksize',
        'total_bandwidth(MiB/s)',
        'total_iops(k)',
        'total_latency(ms)_mean',
        'total_latency(ms)_stdv',
        'read_bandwidth(MiB/s)',
        'read_iops(k)',
        'read_latency(ms)_mean',
        'read_latency(ms)_stdv',
        'write_bandwidth(MiB/s)',
        'write_iops(k)',
        'write_latency(ms)_mean',
        'write_latency(ms)_stdv',
    ]
    # print(df)

    df.to_csv(result_file, header=header, index=False, float_format='%.2f')


def main(parse_file):
    # parser = OptionParser(usage="Usage: %prog <fio result file>")

    # (options, args) = parser.parse_args()
    # /Users/liam/Downloads/a2000/disksdp/normal/ntfs/graid-a2000-ntfs-1vd-randread-j32b4kd32.txt
    # parse_file = args[0]

    if Path(parse_file).is_file():
        print('file')
        parser_diskspd(parse_file)
    elif Path(parse_file).is_dir():
        print('folder')
        parse_file_lst = []
        for entry in Path(parse_file).iterdir():
            if entry.suffix == '.txt':
                parse_file_lst.append(Path(parse_file).joinpath(entry.name))
        for file in parse_file_lst:
            parser_diskspd(file)
        result_folder = create_folder(
            parse_file, Path(parse_file).stem + '/result')
        csv_context = []
        # csv_context.append(Path(parse_file).stem)
        for entry in Path(result_folder).iterdir():
            if entry.suffix == '.csv' and entry.stem[0:8] != 'diskspd-test':
                df = pd.read_csv(Path(result_folder).joinpath(entry.name))
                # print(df)
                for i in range(len(df)):

                    csv_context.append(df.values[i].tolist())

                header = df.keys()
                # print(header)
        df = pd.DataFrame(csv_context).sort_values([2], ascending=True)

        # print(df)
        result_file = Path(result_folder).joinpath('-'.join(
            ['diskspd-test', Path(parse_file).stem, time.strftime('%Y%m%d%H%M%S') + '.csv']))
        df.to_csv(result_file, header=header,
                  index=False, float_format='%.2f')

    else:
        print('error')


def search_and_delete(file_path, search_context):
    file_path = Path(file_path)
    try:
        with file_path.open('r') as file:
            file_contents = file.read()
            if search_context in file_contents:
                file_path.unlink()  # Delete the file
                # print(f"File '{file_path}' deleted.")
            # else:

                # print(f"Search context not found in file '{file_path}'.")
    except FileNotFoundError:
        print(f"File not found: '{file_path}'")


def parser_fio(u_filepath):
    lst = []
    dic = {}
    dic_clat_percentiles = {}
    unit=""
    # print(u_filepath)
    with open(u_filepath) as f:
        file_path = u_filepath  # Replace with the path of your file
        # Replace with the context you want to search
        search_context = "you need to specify size"

        search_and_delete(file_path, search_context)

    try:
        with open(u_filepath) as f:

            lines = f.readlines()
            # print(lines)
            for i in lines:

                # search rw type
                try:
                    if i.split(',')[0].split(':')[2][1:3] == 'rw':
                        lst.append(i.split(',')[0].split(':')[2][4:])
                        dic['Type'] = i.split(',')[0].split(':')[2][4:]
                        # print()
                        # print()
                except:
                    pass
                    # print('error at rw type')
                # search bs
                try:
                    if i.split(',')[1].split('=')[0] == ' bs':
                        if 'KiB' in i.split(',')[3].split('(T)')[
                                1].split('-')[0][1:]:
                            lst.append(float(i.split(',')[3].split('(T)')[
                                1].split('-')[0][1:-3]))
                            dic['BlockSize'] = float(i.split(',')[3].split('(T)')[
                                1].split('-')[0][1:-3])
                        elif i.split(',')[3].split('(T)')[
                                1].split('-')[0][-1:] == 'B':
                            lst.append(float(i.split(',')[3].split('(T)')[
                                1].split('-')[0][1:-1])/1024)
                            dic['BlockSize'] = float(i.split(',')[3].split('(T)')[
                                1].split('-')[0][1:-1])/1024
                except:
                    pass
                    # print('error at bs')
                # search depth
                try:
                    if i.split(',')[-1].split('=')[0] == ' iodepth':
                        lst.append(
                            i.split(',')[-1].split('=')[1].split('\n')[0])
                        dic['Queue Depth'] = (
                            i.split(',')[-1].split('=')[1].split('\n')[0])
                except:
                    pass
                    # print('error at depth')
                # search fio version
                try:
                    if i[0:3] == 'fio':
                        lst.append(i.split('\n')[0])
                        dic['fio-version'] = i.split('\n')[0]
                except:
                    pass
                    # print('error at fio version')
                # search jobs
                try:
                    if i.split(':')[1].split(',')[1].split('=')[0] == ' jobs':
                        # print(, lst[0])
                        lst.append(i.split(':')[1].split(
                            ',')[1].split('=')[1][:-1])
                        dic['Threads'] = i.split(':')[1].split(
                            ',')[1].split('=')[1][:-1]

                except:
                    pass
                    # print('error at jobs')
                # search rw performance
                try:

                    if 'write' in i.split(':')[0]:

                        if (i.split(':')[1].split(',')[0].split('=')[1][-1:]) == 'k':
                            lst.append(float(i.split(':')[1].split(',')[
                                0].split('=')[1][:-1]))
                            dic['IOPs(write)'] = float(i.split(':')[1].split(',')[
                                0].split('=')[1][:-1])

                        elif (i.split(':')[1].split(',')[0].split('=')[1][-1:]) == 'M':
                            lst.append(float(i.split(':')[1].split(',')[
                                0].split('=')[1][:-1])*1000)
                            dic['IOPs(write)'] = float(i.split(':')[1].split(',')[
                                0].split('=')[1][:-1])*1000
                        else:
                            #print(float(i.split(':')[1].split(',')[
                            #    0].split('=')[1])/1000
                            #)
                            lst.append(float(i.split(':')[1].split(',')[
                                0].split('=')[1][:])/1000)
                            dic['IOPs(write)'] = float(i.split(':')[1].split(',')[
                                0].split('=')[1])/1000

                        if 'MiB/s' in (i.split(':')[1].split(',')[1].split('=')[1].split('(')[0]):
                            lst.append(float(i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[0][:-6])/1024)
                            dic['BW(write)-GiB/s'] = float(i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[0][:-6])/1024
                        if 'GiB/s' in (i.split(':')[1].split(',')[1].split('=')[1].split('(')[0]):
                            lst.append(float(i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[0][:-6]))
                            dic['BW(write)-GiB/s'] = float(i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[0][:-6])

                        if (i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[1][-5:-1]) == 'MB/s':
                            lst.append(float(i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[1][:-5])/1000)
                            dic['BW(write)-GB/s'] = float(i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[1][:-5])/1000
                        if (i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[1][-5:-1]) == 'GB/s':
                            lst.append(float(i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[1][:-5]))
                            dic['BW(write)-GB/s'] = float(i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[1][:-5])
                except:
                    pass
                    # print('error at bw_w/IOPs_r')

                try:
                    if 'read' in i.split(':')[0]:

                        if (i.split(':')[1].split(',')[0].split('=')[1][-1:]) == 'k':
                            lst.append(float(i.split(':')[1].split(',')[
                                0].split('=')[1][:-1]))
                            dic['IOPs(read)'] = float(i.split(':')[1].split(',')[
                                0].split('=')[1][:-1])

                        elif (i.split(':')[1].split(',')[0].split('=')[1][-1:]) == 'M':
                            lst.append(float(i.split(':')[1].split(',')[
                                0].split('=')[1][:-1])*1000)
                            dic['IOPs(read)'] = float(i.split(':')[1].split(',')[
                                0].split('=')[1][:-1])*1000
                        else:
                            #print(float(i.split(':')[1].split(',')[
                            #    0].split('=')[1])/1000
                            #)
                            lst.append(float(i.split(':')[1].split(',')[
                                0].split('=')[1][:])/1000)
                            dic['IOPs(read)'] = float(i.split(':')[1].split(',')[
                                0].split('=')[1])/1000

                        if 'MiB/s' in (i.split(':')[1].split(',')[1].split('=')[1].split('(')[0]):
                            lst.append(float(i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[0][:-6])/1024)
                            dic['BW(read)-GiB/s'] = float(i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[0][:-6])/1024
                        if 'GiB/s' in (i.split(':')[1].split(',')[1].split('=')[1].split('(')[0]):
                            lst.append(float(i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[0][:-6]))
                            dic['BW(read)-GiB/s'] = float(i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[0][:-6])

                        if (i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[1][-5:-1]) == 'MB/s':
                            lst.append(float(i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[1][:-5])/1000)
                            dic['BW(read)-GB/s'] = float(i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[1][:-5])/1000
                        if (i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[1][-5:-1]) == 'GB/s':
                            lst.append(float(i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[1][:-5]))
                            dic['BW(read)-GB/s'] = float(i.split(':')[1].split(',')[
                                1].split('=')[1].split('(')[1][:-5])
                except:
                    pass
            # search lats
                try:
                    if "lat" in i.split(':')[0]:

                        lst.append(float(i.split(':')[1].split(',')[2][5:]))
                        lst.append(float(i.split(':')[1].split(',')[3][7:-2]))

                        # print(dic['IOPs(write)'] == "")

                        # print('1324')
                        try:
                            if not dic['IOPs(read)'] == "":
                                if "(usec)" in i.split(':')[0]:
                                    dic['lat_avg(read)[usec]'] = float(
                                            i.split(':')[1].split(',')[2][5:])
                                    dic['lat_stdev(read)[usec]'] = float(
                                            i.split(':')[1].split(',')[3][7:-2])
                                elif "(msec)" in i.split(':')[0]:
                                    dic['lat_avg(read)[usec]'] = float(
                                            i.split(':')[1].split(',')[2][5:])*1000
                                    dic['lat_stdev(read)[usec]'] = float(
                                            i.split(':')[1].split(',')[3][7:-2])*1000
                                elif "(nsec)" in i.split(':')[0]:
                                    dic['lat_avg(read)[usec]'] = float(
                                            i.split(':')[1].split(',')[2][5:])/1000
                                    dic['lat_stdev(read)[usec]'] = float(
                                            i.split(':')[1].split(',')[3][7:-2])/1000

                        except:
                            pass
                            # print('error at lat_r')

                        try:
                            # print(dic['lat_avg(write)[usec]'] != "")
                            if dic['IOPs(write)'] != "":
                                 if "(usec)" in i.split(':')[0]:
                                     dic['lat_avg(write)[usec]'] = float(
                                             i.split(':')[1].split(',')[2][5:])
                                     dic['lat_stdev(write)[usec]'] = float(
                                             i.split(':')[1].split(',')[3][7:-2])
                                 elif "(msec)" in i.split(':')[0]:
                                     dic['lat_avg(write)[usec]'] = float(
                                             i.split(':')[1].split(',')[2][5:])*1000
                                     dic['lat_stdev(write)[usec]'] = float(
                                             i.split(':')[1].split(',')[3][7:-2])*1000
                                 elif "(nsec)" in i.split(':')[0]:
                                     dic['lat_avg(write)[usec]'] = float(
                                             i.split(':')[1].split(',')[2][5:])/1000
                                     dic['lat_stdev(write)[usec]'] = float(
                                             i.split(':')[1].split(',')[3][7:-2])/1000
                        except:
                            pass
                except:
                    pass
                
                percentile_pattern = re.compile(r'(\d+\.\d+th)=\[\s*(\d+)\]')
                if 'clat percentiles (nsec)' in i:
                    unit=0.001
                elif 'clat percentiles (usec)' in i:
                    unit=1
                elif 'clat percentiles (msec)' in i:
                    unit=1000

                #print(i)
                if "th=[" in i:
                    #print(i)
                    matches = percentile_pattern.findall(i)
                    for match in matches:
                        percentile_key, value = match
                        #print(percentile_key.strip(), value)
                        
                        dic_clat_percentiles[percentile_key.strip()] = float(value.strip())*unit
                        #dic['clat_percentiles'][percentile.strip()] = float(value.strip('[],'))
                        #print(dic['clat_percentiles'][percentile_key.strip()])

                #print(dic['clat_percentiles'])

                    # print('error at lat')
            # find cpu%
                # try:

                #         # lst.append(float(i.split(':')[1].split(',')[0][5:-1]))
                #         # lst.append(float(i.split(':')[1].split(',')[1][5:-1]))
                #         # dic['User CPU'] = float(
                #         #     i.split(':')[1].split(',')[0][5:-1])
                #         # dic['System CPU'] = float(
                #         #     i.split(':')[1].split(',')[1][5:-1])

                # except:
                #     pass
                    # print(float(i.split(':')[1].split(',')[0][5:-1]))

            txt_file_path = Path(u_filepath)
            base_name = txt_file_path.stem
            directory = txt_file_path.parent / 'iostat'
            # preprocess_iostat_files(directory)
            # directory_2 = txt_file_path.parents[2].stem

            # directory = txt_file_path.parent
            # directory_2 = txt_file_path
            # print(directory)
            # print(12345)
            # print(directory_2)

            iostat_file_path = directory / f"{base_name}.iostat"

            # iostat_file_path = directory / f"{directory_2}-{base_name}.iostat"

            dic_cpu = {}
            #print(123)
            #print(iostat_file_path)
            dic_cpu = parse_iostat_file(iostat_file_path)
            # print(dic)

            dic['User CPU'] = dic_cpu['avg_user']
            dic['System CPU'] = dic_cpu['avg_system']
            dic['Idle CPU'] = dic_cpu['avg_idle']

            df = pd.DataFrame(dic, index=[0])
            df_dic_clat_percentiles = pd.DataFrame(dic_clat_percentiles, index=[0])

            # Ensure all expected columns exist with default value 0/N/A
            expected_cols = {
                'BW(read)-GB/s': 0.0, 'BW(read)-GiB/s': 0.0, 'IOPs(read)': 0.0, 
                'lat_avg(read)[usec]': 0.0, 'lat_stdev(read)[usec]': 0.0,
                'BW(write)-GB/s': 0.0, 'BW(write)-GiB/s': 0.0, 'IOPs(write)': 0.0,
                'lat_avg(write)[usec]': 0.0, 'lat_stdev(write)[usec]': 0.0,
                'Threads': 'N/A', 'BlockSize': 'N/A', 'Queue Depth': 'N/A',
                'User CPU': 0.0, 'System CPU': 0.0, 'Idle CPU': 0.0,
                'fio-version': 'N/A', 'Type': 'N/A'
            }
            for col, default in expected_cols.items():
                if col not in df.columns:
                    df[col] = default

            # Consolidate metrics (Summing works for Read, Write, or Mixed since missing are 0)
            df['Bandwidth (GB/s)'] = round(df['BW(read)-GB/s'] + df['BW(write)-GB/s'], 2)
            df['Bandwidth (GiB/s)'] = round(df['BW(read)-GiB/s'] + df['BW(write)-GiB/s'], 2)
            df['IOPS(K)'] = round(df['IOPs(read)'] + df['IOPs(write)'], 0)
            df['Latency (us)'] = round(df['lat_avg(read)[usec]'] + df['lat_avg(write)[usec]'], 0)
            df['Latency_stdev (us)'] = round(df['lat_stdev(read)[usec]'] + df['lat_stdev(write)[usec]'], 0)
            # print(df.keys(), df)

            df.rename({"lat_avg(read)[usec]": "Read Latency (us)",
                       "lat_avg(write)[usec]": "Write Latency (us)",
                       }, axis=1, inplace=True)

            df_name = set_dataframe(df, u_filepath)
            
            # Ensure percentile columns exist
            percentile_cols = [
                '1.00th', '5.00th', '10.00th', '20.00th', '30.00th', '40.00th', '50.00th', 
                '60.00th', '70.00th', '80.00th', '90.00th', '95.00th', '99.00th', '99.50th', 
                '99.90th', '99.95th', '99.99th'
            ]
            for col in percentile_cols:
                if col not in df_dic_clat_percentiles.columns:
                    df_dic_clat_percentiles[col] = 0.0
                    
            df_n = pd.concat([df_name, df, df_dic_clat_percentiles], axis=1)
            #print(df_n)
            df_n = df_n[[
                'Model',
                'controller',
                'fio-version',
                'SSD',
                'Ben_type',
                'Type',
                'RAID_status',
                "WriteCache",
                "Tasks_number",
                'RAID_type',
                'PD_count',
                'stage',
                'Threads',
                'BlockSize',
                'Queue Depth',
                'Bandwidth (GB/s)',
                'IOPS(K)',
                'Read Latency (us)',
                'Write Latency (us)',
                'System CPU',
                'User CPU',
                'Idle CPU',
                'Bandwidth (GiB/s)',
                '1.00th','5.00th','10.00th','20.00th',
                '30.00th','40.00th','50.00th','60.00th',
                '70.00th','80.00th','90.00th','95.00th',
                '99.00th','99.50th','99.90th','99.95th',
                '99.99th',
            ]]
            result_folder = create_folder(u_filepath, 'result')
            result_file = Path(result_folder).joinpath(''.join(
                ['fio-test-', Path(u_filepath).stem, '-',  time.strftime("%Y%m%d_%H%M"), '_fio', '.csv']))
        # print(result_file)
        # print((df_t.keys().tolist()))
        # print(len(header))
        df_n.to_csv(result_file, header=df_n.keys(),
                    index=True, float_format='%.2f')
    except FileNotFoundError:
        print(f"File not found: '{file_path}'")


def collect_data(u_file_path, query_id, file_hder, save_folder_name):

    global df_header
    # print('enter collection')
    result_folder = create_folder(
        u_file_path, Path(u_file_path).stem + '/' + str(save_folder_name))
    csv_context = []
    result_file_lst = [x for x in Path(
        u_file_path).rglob('*') if x.suffix == '.csv' and x.stem[0:(len(query_id))] == query_id]

    for entry in result_file_lst:
        # print(entry)

        if entry.suffix == '.csv' and entry.stem[0:(len(query_id))] == query_id:
            # print('123', entry)
            df = pd.read_csv(entry)

            for i in range(len(df)):

                # csv_context.append(
                #     df.values[i].tolist())
                a = Path(entry).stem
                b = df.values[i].tolist()
                c = b.insert(0, a)
                csv_context.append(b)

            df_header = df.keys().tolist()
            header_1 = df_header.insert(0, 'filename')
            # print(df_header)
    df = pd.DataFrame(csv_context, columns=df_header,
                      )
    # df = pd.DataFrame(csv_context).sort_values(
    #     [8, 2, 5, 9, 6, 7, 12, 4], ascending=True)
    # df_t.sort_values(by=['VD_count', 'job options.bs', 'job options.rw'])
    # print(df)
    # print(df)
    if df['stage'][0] == "":

        sorted_lst = ['controller', 'RAID_status', 'Tasks_number', 'WriteCache', 'PD_count',
                      'RAID_type', 'Threads', 'BlockSize', 'Queue Depth', 'Ben_type']
    elif df['stage'][0] != "":
        sorted_lst = ['controller', 'RAID_status', 'Tasks_number', 'WriteCache', 'PD_count', 'stage',
                      'RAID_type', 'Threads', 'BlockSize', 'Queue Depth', 'Ben_type']

    df_sorted = df.sort_values(
        by=sorted_lst, ascending=True)
    # print(df['SSD'][0])
    result_file = Path(result_folder).joinpath('-'.join(
        [file_hder, Path(u_file_path).stem, str(df['SSD'][0]), time.strftime('%Y%m%d%H%M%S') + '.csv']))
    # print(df_sorted.keys())
    df_sorted.to_csv(result_file, header=df_sorted.keys().tolist(),
                     index=False, float_format='%.2f')

    # df.to_csv(result_file, header=df_header,
    #           index=False, float_format='%.2f')
    return result_file


def read_file(u_file_path, u_file_type):

    global df_header

    # print(u_file_path, u_file_type)

    if Path(u_file_path).is_file():
        # print('file')
        parser_fio(u_file_path)
    elif Path(u_file_path).is_dir():
        # print('folder')
        parse_file_lst = []
        parse_file_lst = [x for x in Path(
            # u_file_path).rglob('*') if x.suffix == '.txt']

            u_file_path).rglob('*') if x.suffix == u_file_type]
        # parse_iostat_lst = [x for x in Path(
        #     # u_file_path).rglob('*') if x.suffix == '.txt']

        #     u_file_path).rglob('*') if x.suffix == '.iostat']
        # print(parse_file_lst)
        for file in parse_file_lst:
            parser_fio(file)

        collect_data(u_file_path, 'fio', 'fio-test-r', 'result')


def parse_iostat_file(file_path):
    with open(file_path, 'r') as file:
        lines = file.readlines()

    # Initialize total counters
    total_user = total_nice = total_system = total_iowait = total_steal = total_idle = count = 0

    # Flag to start collecting data
    start_collecting = False

    for line in lines:
        if "avg-cpu" in line:
            start_collecting = True
            continue
        if start_collecting:
            values = line.split()
            if len(values) == 6:
                total_user += float(values[0])
                total_nice += float(values[1])
                total_system += float(values[2])
                total_iowait += float(values[3])
                total_steal += float(values[4])
                total_idle += float(values[5])
                count += 1
            else:
                start_collecting = False

    # Calculate averages
    avg_user = total_user / count if count else 0
    avg_nice = total_nice / count if count else 0
    avg_system = total_system / count if count else 0
    avg_iowait = total_iowait / count if count else 0
    avg_steal = total_steal / count if count else 0
    avg_idle = total_idle / count if count else 0

    # Return results
    return {
        'avg_user': "{:.2f}".format(avg_user),
        'avg_nice': "{:.2f}".format(avg_nice),
        'avg_system': "{:.2f}".format(avg_system),
        'avg_iowait': "{:.2f}".format(avg_iowait),
        'avg_steal': "{:.2f}".format(avg_steal),
        'avg_idle': "{:.2f}".format(avg_idle),
    }







def parser_filename(u_file_path):
    u_name = Path(u_file_path).stem.split('-')

    # Initialize default values
    device = fio_type = model = status = RAID_type = PD_count = stage = controller = Jobs = wt = "N/A"

    try:
        # Find critical indices
        vd_indices = [i for i, x in enumerate(u_name) if x.endswith('VD')]
        if not vd_indices:
            raise ValueError("No VD token found")
        vd_idx = vd_indices[0] # Assume first VD match is the one

        pd_idx = -1
        # Look for PD around VD
        if len(u_name) > vd_idx + 1 and u_name[vd_idx+1].endswith('PD'):
            pd_idx = vd_idx + 1
        
        # PD Count
        if pd_idx != -1:
             PD_count = u_name[pd_idx][:-2] # Remove 'PD'
        
        # Find S and D indices
        s_indices = [i for i, x in enumerate(u_name) if x == 'S']
        d_indices = [i for i, x in enumerate(u_name) if x == 'D']
        
        s_idx = s_indices[0] if s_indices else -1
        d_idx = d_indices[-1] if d_indices else -1 # Use last D as Stage separator usually comes later?
        # Actually usually ...-S-Device-D-Stage...
        # If there are multiple Ds (e.g. inside Device name?), take the one after S?
        if s_idx != -1:
             possible_d = [i for i in d_indices if i > s_idx]
             if possible_d:
                 d_idx = possible_d[0]
        
        # Device extraction
        if s_idx != -1 and d_idx != -1 and d_idx > s_idx:
            device = "-".join(u_name[s_idx+1 : d_idx])
        
        # Filesystem detection to isolate RAID Type
        fs_list = ['RAW', 'NTFS', 'EXT4', 'XFS', 'BTRFS', 'ZFS']
        fs_idx = -1
        for i, token in enumerate(u_name):
            if token in fs_list:
                fs_idx = i
                break
        
        # RAID Type Extraction
        if fs_idx != -1 and vd_idx > fs_idx:
            # Everything between FS and VD
            RAID_type = "-".join(u_name[fs_idx+1 : vd_idx])
        else:
             # Fallback: Start from roughly index 3?
             # If graid-SR-RAID5-1VD (No FS?)
             # Assume GRAID-Controller-FS-RAID-VD
             # If FS is missing, maybe between Controller and VD?
             # Checking bench.sh, FS seems mandatory.
             # If not found, use heuristic: tokens before VD
             # ex: graid-SR-RAW-RAID5-1VD -> RAW is FS.
             # If we didn't find known FS, maybe index 2 is FS?
             # Let's trust bench.sh puts FS there.
             # If tokens[2] is not FS, then we might have issue.
             # But let's try to grab token before VD?
             if vd_idx > 3:
                 RAID_type = u_name[vd_idx-1]
                 # If RAID type has multiple tokens (SR-CRAID)
                 # We need better start point.
                 # If controller is at 1.
                 # Start from 2 (FS?) + 1?
                 pass

        # Controller and Model
        # graid-{Controller}-{FS}-{RAID}...
        # If FS found at fs_idx.
        # Controller is tokens[1:fs_idx] joined?
        if fs_idx > 1:
             # u_name[0] is graid
             # u_name[1] starts controller
             controller = "-".join(u_name[1:fs_idx])
             # logic in original parser separates 'Model' from 'Controller' if it splits?
             # original: controller=u_name[0+i] (graid? no i=1 means SR).
             # if i=1, controller = u_name[1] = SR.
             # model = u_name[2] = RAW?
             # The original parser semantics for Controller/Model on 'SR' were dubious.
             # Let's try to map 'SR' to Controller if it starts with SR?
             pass
        elif fs_idx == -1 and vd_idx > 2:
             # Guess controller is 1?
             controller = u_name[1]


        # Original Logic emulation for controller/model to minimize regression
        if u_name[1] == 'SR':
             # Preserve 'SR' as controller?
             # original code: i=1. controller = u_name[i] -> SR. 
             # model = u_name[i+1] -> u_name[2].
             # If file is graid-SR-RAW-RAID5...
             # Controller=SR, Model=RAW.
             # If file is graid-SR-ULTRA-AD-RAW...
             # Controller=SR, Model=ULTRA?
             # If FS is found, we might want to be smarter.
             pass
        
        # Stage, Type, Status extraction
        # After D: Stage
        if d_idx != -1 and len(u_name) > d_idx + 1:
             stage = u_name[d_idx+1]
        
        
        # Status Parsing: Search from the end for known status keywords
        status_keywords = ['Normal', 'Rebuild', 'Resync']
        status_idx = -1
        # Check last 4 tokens (covering cases with/without J/D)
        for i in range(1, min(len(u_name) + 1, 6)):
             if u_name[-i] in status_keywords:
                 status = u_name[-i]
                 status_idx = len(u_name) - i
                 break
        
        # Jobs and Wait Time
        # Usually after Status if they exist.
        if status_idx != -1:
             remaining = u_name[status_idx+1:]
             # Parse remaining tokens for J and D
             for token in remaining:
                 if token.endswith('J') or token.endswith('k'):
                     Jobs = token
                 elif token.endswith('D') or token.endswith('s') or token.endswith('M'): # wt might be 4D or similar?
                     wt = token
        
        # Fio Type Extraction
        # Between Stage and Status
        if d_idx != -1:
             start_type = d_idx + 2
             end_type = status_idx if status_idx != -1 else len(u_name)
             
             if start_type < end_type:
                  type_tokens = u_name[start_type : end_type]
                  # Clean up tokens
                  clean_tokens = []
                  for t in type_tokens:
                      if t in ['BS', 'BSALL', 'grai', 'graid']:
                          continue
                      # Filter purely numeric sorting prefixes like '00', '01' if they lack semantic meaning?
                      # But wait, '00' might be important? User didn't complain about '00'.
                      # User complained about "Ben_type missing" and distinguishing randrw55/73.
                      # Ideally we extract 'randread', 'seqwrite', 'randrw73' etc.
                      # Let's keep it simple: filter known junk.
                      if t.isdigit() and len(t) <= 3: # heuristics for 00, 01
                           continue 
                      clean_tokens.append(t)
                  
                  if clean_tokens:
                      fio_type = "-".join(clean_tokens)
                  else:
                      # If cleanup removed everything, revert to raw join
                      fio_type = "-".join(type_tokens)

        # Overwrite Controller logic specific to MD case from original
        if len(Path(u_file_path).parts) >= 3 and Path(u_file_path).parts[-3] == 'MD':
            controller = 'MD'
        
        # Cleanup fallback
        if controller == "N/A" and len(u_name) > 1:
             controller = u_name[1]
             
        # Refine Model
        if model == "N/A" and controller == "SR" and fs_idx > 2:
             model = "-".join(u_name[2:fs_idx])
        elif model == "N/A" and len(u_name) > 2:
             model = u_name[2]

    except Exception as e:
        print(f"Error parsing filename {u_file_path}: {e}")
        pass

    filename_lst = [device, status, RAID_type, PD_count, stage, fio_type, Jobs, wt, controller, model]

    return filename_lst


if __name__ == '__main__':

    if len(sys.argv) != 2:
        print("Usage: python3 fio_parser.py <path_to_fio_logs>")
    else:
        # main(sys.argv[1])

        # path = '/Users/liam/Downloads/a2000/disksdp/normal/ntfs/graid-a2000-ntfs-1vd-randread-j32b4kd32.txt'
        parse_file = sys.argv[1]

        # preprocess_iostat_files(parse_file)
        rm_folder(parse_file, 'result')
        rm_folder(parse_file, 'comparison_data')
        rm_folder(parse_file, 'query_result')
        u_name = Path(parse_file).stem.split('-')
        # print(u_name[-1].split('_')[-2])
        read_file(parse_file, '.txt')
        # query_data(parse_file)

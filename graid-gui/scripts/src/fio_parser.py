
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
            #print(df_dic_clat_percentiles)

            if 'BW(write)-GB/s' not in df:
                # print(dic)
                df['Bandwidth (GB/s)'] = round(df['BW(read)-GB/s'], 2)
                df['Bandwidth (GiB/s)'] = round(df['BW(read)-GiB/s'], 2)
                df['IOPS(K)'] = round(df['IOPs(read)'], 0)
                df['Latency (us)'] = round(df['lat_avg(read)[usec]'], 0)
                df['Latency_stdev (us)'] = round(
                    df['lat_stdev(read)[usec]'], 0)

                df['BW(write)-GB/s'] = 0
                df['BW(write)-GiB/s'] = 0
                df['IOPs(write)'] = 0
                df['lat_avg(write)[usec]'] = 0
                df['lat_stdev(write)[usec]'] = 0

            elif 'BW(read)-GB/s' not in df:

                df['Bandwidth (GB/s)'] = round(
                    df['BW(write)-GB/s'], 2)
                df['Bandwidth (GiB/s)'] = round(df['BW(write)-GiB/s'], 2)
                # print(df)
                df['IOPS(K)'] = round(df['IOPs(write)'], 0)
                df['Latency (us)'] = round(
                    df['lat_avg(write)[usec]'], 0)
                df['Latency_stdev (us)'] = round(
                    df['lat_stdev(write)[usec]'], 0)

                df['BW(read)-GB/s'] = 0
                df['BW(read)-GiB/s'] = 0
                df['IOPs(read)'] = 0
                df['lat_avg(read)[usec]'] = 0
                df['lat_stdev(read)[usec]'] = 0

            else:
                df['Bandwidth (GB/s)'] = round(df['BW(read)-GB/s'] +
                                               df['BW(write)-GB/s'], 2)
                df['Bandwidth (GiB/s)'] = round(df['BW(read)-GiB/s'] +
                                                df['BW(write)-GiB/s'], 2)
                df['IOPS(K)'] = round(df['IOPs(read)'] + df['IOPs(write)'], 0)
                df['Latency (us)'] = round(df['lat_avg(read)[usec]'] +
                                           df['lat_avg(write)[usec]'], 0)
                df['Latency_stdev (us)'] = round(df['lat_stdev(read)[usec]'] +
                                                 df['lat_stdev(write)[usec]'], 0)
            # print(df.keys(), df)

            df.rename({"lat_avg(read)[usec]": "Read Latency (us)",
                       "lat_avg(write)[usec]": "Write Latency (us)",
                       }, axis=1, inplace=True)

            df_name = set_dataframe(df, u_filepath)
            df_n = pd.concat([df_name, df,df_dic_clat_percentiles ], axis=1)
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

    if u_name[1] == 'SR':
        i = 1
    else:
        i = 0

    # Find the SSD
    b_ = u_name.index('S') + 1
    f_ = u_name.index('D')

    # Device
    if 'BS' in u_name:
        ba_ = u_name.index('BS')
        device = u_name[ba_ + 1]
    else:
        device = "-".join(u_name[b_:f_])

    # Function type
    if 'BSALL' in u_name:
        fio_type = u_name[f_ + 4]
    elif 'BS' in u_name:
        fio_type = u_name[ba_ + 3]
    else:
        fio_type = u_name[f_ + 2]

    # Graid Model
    model = u_name[1 + i]

    # RAID status and RAID type
    if '8k' in u_name or '16k' in u_name:
        RAID_type = u_name[3 + i]
        PD_count = u_name[5 + i][:-2]
    else:
        RAID_type = u_name[3 + i]
        PD_count = u_name[5 + i][:-2]

    if 'BSALL' in u_name:
        status = u_name[f_ + 6]
    elif 'BS' in u_name:
        status = u_name[ba_ + 5]
    else:
        status = u_name[f_ + 4]

    # Stage
    stage = u_name[f_ + 1]

    # Controller
    if Path(u_file_path).parts[-3] == 'MD':
        controller = 'MD'
    else:
        controller = u_name[0 + i]

    # Jobs and Wait Time
    Jobs = u_name[-2]
    wt = u_name[-1]

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

### import packages
import requests
import json
import pandas as pd
from arctic import Arctic
import pywt
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns; sns.set()
import warnings
warnings.filterwarnings("ignore")
from sklearn import cluster
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import KNeighborsClassifier
from sklearn import metrics
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.ensemble import RandomForestClassifier

### Downdoad Data
# function that gets data from Polygon.io
def get_data(time_from, time_to):
    # specify the six currency pairs desired and other parameters
    target_currency_pairs = ["C:EURUSD", "C:GBPEUR", "C:CNYUSD", "C:USDCHF", "C:USDCAD", "C:USDAUD"]
    api = "beBybSi8daPgsTp5yx5cHtHpYcrjp5Jq"
    multiplier = "6"
    timespan = "minute"
    time_from = time_from
    time_to = time_to
    limit = "5000"
    
    # loop through all currency pairs
    for i in range(len(target_currency_pairs)):
        api_url = f"https://api.polygon.io/v2/aggs/ticker/{target_currency_pairs[i]}/range/{multiplier}/{timespan}/{time_from}/{time_to}?adjusted=true&sort=asc&limit={limit}&apiKey={api}"
        data = requests.get(api_url).json()
        
        results_count = data["resultsCount"]
        for v in range(results_count):
            # convert key-value format to table format
            # FX rate computed as the average of the highest and lowest price in every 6 minutes
            row_result = [data["results"][v]["t"], data["ticker"], (data["results"][v]["h"] + data["results"][v]["l"]) / 2]
            #append the row to result_df
            result_df.loc[len(result_df)] = row_result


# Save Date inside MongoDB
def write_to_db(df, library_name, symbol_name):
    global library
    # connect to MongoDB using Arctic
    store = Arctic("localhost")
    # create the library - defaults to VersionStore
    store.initialize_library(library_name)
    # access the library
    library = store[library_name]
    # store the data in the library
    library.write(symbol_name, df)

# Communicate Between MongoDB and Python
# reading the data
def read_data(symbol_name):
    item = library.read(symbol_name)
    df = item.data
    return df

# set a time column
def set_time_column(df):
    df["time"] = pd.to_datetime(df["timestamp"], unit = "ms")
    df["time"] = df["time"].astype("datetime64[m]")
    
### Get training dataset
# creating an empty DataFrame to store the data
result_df = pd.DataFrame(columns = ["timestamp","currency_pair","FX_rate"])

# PART1: Downdoad Data
get_data("2021-11-29", "2021-12-01")

# PART2: Save Date inside Database
write_to_db(result_df, "project", "training_df")

# PART3: Communicate Between Database and Python 
# read the data back from MongoDB
training_df = read_data("training_df")

# set a time column
set_time_column(training_df)

### Sanity check
def sanity_check(df):
    "Do a sanity check of all new data coming to your time series."
    print(df.head())
    print(df.groupby(['currency_pair']).describe())
    print(f"If any missing values in fx rate? {df['FX_rate'].isnull().values.any()}")
    print(f"Number of missing values in fx rate: {df['FX_rate'].isnull().values.sum()}")
    
sanity_check(training_df)

### Get testing dataset
# creating an empty DataFrame to store the data
result_df = pd.DataFrame(columns = ["timestamp","currency_pair","FX_rate"])

# Downdoad Data
get_data("2021-12-02", "2021-12-02")

# Save Date inside Database
write_to_db(result_df, "project", "testing_df")

# Communicate Between Database and Python 
# read the data back from MongoDB
testing_df = read_data("testing_df")

# set a time column
set_time_column(testing_df)

# Sanity check
sanity_check(testing_df)

# Continuous Wavelet Transform (CWT)
wavelet_name = "gaus5"
scales = np.arange(0.1,1,0.1)
currency_and_label = {"C:EURUSD":[0,1], 
                      "C:GBPEUR":[3,0], 
                      "C:CNYUSD":[0,3], 
                      "C:USDCHF":[2,3], 
                      "C:USDCAD":[2,3], 
                      "C:USDAUD":[2,0]}

for currency_pair in training_df["currency_pair"].unique():
    ### training_df
    currency_df = training_df.loc[training_df["currency_pair"] == currency_pair]
    
    plt.plot(currency_df["time"], currency_df["FX_rate"])
    plt.title(currency_pair)
    
    max_value = max(currency_df["FX_rate"])
    min_value = min(currency_df["FX_rate"])
    data_range = max_value - min_value
    
    plt.ylim([min_value - 0.7 * data_range, max_value + 0.7 * data_range])
    plt.show()
    
    # Histograms helps to understand distribution of data which in return helps in forecasting a variable
    plt.hist(currency_df["FX_rate"])
    plt.show()
    
    # compute return
    # create a new column return
    previous = currency_df["FX_rate"].shift(1)
    currency_df["return"] = (currency_df["FX_rate"] - previous) / previous
    currency_df["return"] = currency_df["return"].fillna(0)
    
    signal = currency_df["return"]
    signal_ext = pd.concat([signal.iloc[:100][::-1], signal, signal.iloc[::-1][:100]])
    
    coef, freq = pywt.cwt(signal_ext, scales, wavelet_name)
    coef = coef[:, 100:-100]
    df_coef = pd.DataFrame(coef).T
    print(df_coef.shape)
    
    # Clustering
    df_coef = df_coef.dropna(axis=0)
    
    params = {"n_clusters": 4}
    spectral = cluster.SpectralClustering(n_clusters = params['n_clusters'],
                                          eigen_solver = "arpack",
                                          affinity = "nearest_neighbors",
                                          assign_labels = "discretize",
                                          random_state = 42)

    X = np.array(df_coef)

    X = StandardScaler().fit_transform(X)

    spectral.fit(X)
    y_pred = spectral.labels_.astype(int)
    
    # add label to currency_df
    currency_df["cwt_cluster_label"] = y_pred
    
    # create a new column next_return 
    # create a new column positive_return
    # 1 if increasing in next 6 minutes; else 0
    currency_df["next_return"] = currency_df["return"].shift(-1)
    currency_df["positive_return"] = 0
    currency_df.loc[currency_df["next_return"] > 0, "positive_return"] = 1
    
    # Basic statistics for each cluster
    # average return for each cluster
    print('Average return for each cluster is:')
    print(currency_df.groupby(["cwt_cluster_label"])["next_return"].mean())
    # standard deviation for each cluster
    print('Standard deviation for each cluster is:')
    print(currency_df.groupby(["cwt_cluster_label"])["next_return"].std())
    # average time duration for each cluster; unit: minutes
    print('Average time duration for each cluster in minutes is:')
    print(6 * currency_df.groupby(["cwt_cluster_label"])["positive_return"].count())
    # group by the cluster label and compute avereage of postive_return which is either 1 or 0
    # get the increase possibility of the clusters in next 6 minutes 
    print('The possibility of getting a positive return is: ')
    print(currency_df.groupby(["cwt_cluster_label"])["positive_return"].mean())
    
    # boxplot shows the result of each cluster
    sns.boxplot(x='cwt_cluster_label',y='next_return', data=currency_df)
    plt.title(currency_pair)
    plt.show()
    
    ### testing_df
    currency_testing_df = testing_df.loc[testing_df["currency_pair"] == currency_pair]
    
    # compute return
    # create a new column return
    previous = currency_testing_df["FX_rate"].shift(1)
    currency_testing_df["return"] = (currency_testing_df["FX_rate"] - previous) / previous
    currency_testing_df["return"] = currency_testing_df["return"].fillna(0)
    
    signal = currency_testing_df["return"]
    signal_ext = pd.concat([signal.iloc[:100][::-1], signal, signal.iloc[::-1][:100]])
    
    coef, freq = pywt.cwt(signal_ext, scales, wavelet_name)
    coef = coef[:, 100:-100]
    testing_df_coef = pd.DataFrame(coef).T
    print(testing_df_coef.shape)
    
    # Clustering
    testing_df_coef = testing_df_coef.dropna(axis=0)
    
    params = {"n_clusters": 4}
    spectral = cluster.SpectralClustering(n_clusters = params['n_clusters'],
                                          eigen_solver = "arpack",
                                          affinity = "nearest_neighbors",
                                          assign_labels = "discretize",
                                          random_state = 42)

    X = np.array(testing_df_coef)

    X = StandardScaler().fit_transform(X)

    spectral.fit(X)
    y_pred = spectral.labels_.astype(int)
    print(y_pred)
    
    # add label to currency_df
    currency_testing_df["cwt_cluster_label"] = y_pred
    
    X_train_ = df_coef
    y_train_ = currency_df["cwt_cluster_label"]
    X_test_ = testing_df_coef
    y_test_ = currency_testing_df["cwt_cluster_label"]
    
    # Classification
    # Classification Method1: k-nearest neighbors algorithm(K-NN)
    # Try running from k=1 through 25 and record testing accuracy
    k_range = range(1,26)
    scores = {}
    scores_list = []
    for k in k_range:    
        knn = KNeighborsClassifier(n_neighbors=k)
        knn.fit(X_train_, y_train_)
        y_pred=knn.predict(X_test_)
        scores[k] = metrics.accuracy_score(y_test_, y_pred)
        scores_list.append(metrics.accuracy_score(y_test_,y_pred))
    
    #plot the relationship between K and the testing accuracy
    plt.plot(k_range, scores_list)
    plt.xlabel("Value of K for KNN")
    plt.ylabel("Testing Accuracy")
    plt.show()
    
    # choose a optimal value of K
    k = max(scores,key=scores.get)
    knn = KNeighborsClassifier(n_neighbors=k)
    knn.fit(X_train_, y_train_)
    y_pred=knn.predict(X_test_)
    score = metrics.accuracy_score(y_test_, y_pred)
    
    print("highest accuracy score: {}".format(score))
    print(classification_report(y_test_, y_pred))
    # Creates a confusion matrix
    cm = confusion_matrix(y_test_, y_pred) 

    # create df and add class names
    labels = [0,1,2,3]
    df_cm = pd.DataFrame(cm,
                     index = labels, 
                     columns = labels)

    # plot figure
    plt.figure(figsize=(5.5,4))
    sns.heatmap(df_cm, cmap="PuBuGn_r", annot=True)

    #add titles and labels for the axes
    plt.title("k-Nearest Neighbors \n{}".format(currency_pair))
    plt.ylabel('Prediction')
    plt.xlabel('Actual Class')
    plt.show()
    
    
    # Classification Method 2:Logistic Regression

    X_train_ = df_coef
    y_train_ = currency_df["cwt_cluster_label"]
    X_test_ = testing_df_coef
    y_test_ = currency_testing_df["cwt_cluster_label"]

    #instantiate classifier object and fit to training data
    # clf = LogisticRegression(solver='lbfgs')
    # Regularized Logistic Regression #
    clf = LogisticRegression(solver='lbfgs', penalty='l2', C=0.5)
    clf.fit(X_train_, y_train_)

    # predict on test set and score the predictions against y_test
    y_pred = clf.predict(X_test_)
    f1 = f1_score(y_test_, y_pred, average='micro') 
    print('f1 score(Logistic Regression) is = ' + str(f1))
    
    # Creates a confusion matrix
    cm = confusion_matrix(y_test_, y_pred) 

    # create df and add class names
    labels = [0,1,2,3]
    df_cm = pd.DataFrame(cm,
                     index = labels, 
                     columns = labels)

    # plot figure
    plt.figure(figsize=(5.5,4))
    sns.heatmap(df_cm, cmap="Purples_r", annot=True)

    #add titles and labels for the axes
    plt.title("Logistic Regression \n{}".format(currency_pair))
    plt.ylabel('Prediction')
    plt.xlabel('Actual Class')
    plt.show()
#     score = metrics.accuracy_score(y_test_, y_pred)
#     print("highest accuracy score(Logistic Regression): {}".format(score))
    
    # Classification Method 3: Random Forest
    #instantiat0e classifier object and fit to training data
    clf = RandomForestClassifier(max_depth=4, n_estimators=4, 
                                 max_features='sqrt', random_state=42)
    clf.fit(X_train_, y_train_)

    # predict on test set and score the predictions against y_test
    y_pred = clf.predict(X_test_)
    f1 = f1_score(y_test_, y_pred, average='micro') 
    print('f1 score (Random Forest) is = ' + str(f1))
    
        # Creates a confusion matrix
    cm = confusion_matrix(y_test_, y_pred) 

    # create df and add class names
    labels = [0,1,2,3]
    df_cm = pd.DataFrame(cm,
                     index = labels, 
                     columns = labels)

    # plot figure
    plt.figure(figsize=(5.5,4))
    sns.heatmap(df_cm, cmap="Purples", annot=True)

    #add titles and labels for the axes
    plt.title("Random Forest \n{}".format(currency_pair))
    plt.ylabel('Prediction')
    plt.xlabel('Actual Class')
    plt.show()
    
#     score = metrics.accuracy_score(y_test_, y_pred)
#     print("highest accuracy score(Random Forest): {}".format(score))
    
    # Trading
    # reset index of currency_testing_df
    currency_testing_df.reset_index(drop = True, inplace = True)
    # Assets Under Management is 100K
    # Assets In Market is 0
    AUM = 100
    AIM = 0
    for i in range(len(currency_testing_df)):
        return_rate = currency_testing_df.loc[i, "return"]
        AIM = AIM * (1 + return_rate)
        if (currency_testing_df.loc[i, "cwt_cluster_label"] == currency_and_label[currency_pair][0]) & (AUM >= 10):
            print("TIME:{} ACTION:BUY".format(currency_testing_df.loc[i, "time"]))
            AUM = AUM - 10
            AIM = AIM + 10
    
        elif (currency_testing_df.loc[i, "cwt_cluster_label"] == currency_and_label[currency_pair][1]) & (AIM >= 10):
            print("TIME:{} ACTION:SELL".format(currency_testing_df.loc[i, "time"]))
            AUM = AUM + 10
            AIM = AIM - 10
        
        else:
            print("TIME:{} ACTION:DO NOTHING".format(currency_testing_df.loc[i, "time"]))

    print("FINAL AUM: " + str(AUM))
    print("FINAL AIM: " + str(AIM))
    print("SUM: " + str(AUM + AIM))

    print("=========================================================") 

    